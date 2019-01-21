from collections import Counter
from collections import deque
from datetime import datetime
import argparse
import copy
import gc
import io
import logging
import os
import pickle
import re
import socket
import time
import random

from google.cloud import storage
from tensorboardX import SummaryWriter
import numpy as np
import pika
import scipy.signal
import torch
import torch.distributed as dist

from distributed import DistributedDataParallelSparseParamCPU
from dotaservice.protos.DotaService_pb2 import TEAM_DIRE, TEAM_RADIANT
from policy import Policy


logging.basicConfig(format='%(asctime)s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

torch.manual_seed(7)

eps = np.finfo(np.float32).eps.item()


def is_distributed():
    return torch.distributed.is_available() and torch.distributed.is_initialized()


def is_master():
    if is_distributed():
        return torch.distributed.get_rank() == 0
    else:
        return True


def discount(x, gamma):
    return scipy.signal.lfilter([1], [1, -gamma], x[::-1], axis=0)[::-1].astype(np.float32)


def normalize(x):
    return (x - x.mean()) / (x.std() + eps)


class MessageQueue:
    EXPERIENCE_QUEUE_NAME = 'experience'
    MODEL_EXCHANGE_NAME = 'model'
    MAX_RETRIES = 10

    def __init__(self, host, port, prefetch_count, use_model_exchange):
        """
        Args:
            prefetch_count (int): Amount of messages to prefetch. Settings this variable too
                high can result in blocked pipes that time out.
        """
        self._params = pika.ConnectionParameters(
            host=host,
            port=port,
            heartbeat=0,
        )
        self.prefetch_count = prefetch_count
        self.use_model_exchange = use_model_exchange

        self._conn = None
        self._xp_channel = None
        self._model_exchange = None

    def process_events(self):
        try:
            self._conn.process_data_events()
        except:
            pass

    def connect(self):
        if not self._conn or self._conn.is_closed:
            # RMQ.
            for i in range(10):
                try:
                    self._conn = pika.BlockingConnection(self._params)
                except pika.exceptions.ConnectionClosed:
                    logger.error('Connection to RMQ failed. retring. ({}/{})'.format(i, self.MAX_RETRIES))
                    time.sleep(5)
                    continue
                else:
                    logger.info('Connected to RMQ')
                    break

            # Experience channel.
            self._xp_channel = self._conn.channel()
            self._xp_channel.basic_qos(prefetch_count=self.prefetch_count)
            self._xp_channel.queue_declare(queue=self.EXPERIENCE_QUEUE_NAME)

            # Model Exchange.
            if self.use_model_exchange:
                self._model_exchange = self._conn.channel()
                self._model_exchange.exchange_declare(
                    exchange=self.MODEL_EXCHANGE_NAME,
                    exchange_type='x-recent-history',
                    arguments={'x-recent-history-length': 1},
                )

    @property
    def xp_queue_size(self):
        try:
            res = self._xp_channel.queue_declare(queue=self.EXPERIENCE_QUEUE_NAME, passive=True)
            return res.method.message_count
        except:
            return None

    def process_data_events(self):
        # Sends heartbeat, might keep conn healthier.
        try:
            self._conn.process_data_events()
        except:  # Gotta catch em' all!
            pass

    def _publish_model(self, msg, hdr):
        self._model_exchange.basic_publish(
            exchange=self.MODEL_EXCHANGE_NAME,
            routing_key='',
            body=msg,
            properties=pika.BasicProperties(headers=hdr),
        )

    def publish_model(self, *args, **kwargs):
        try:
            self._publish_model(*args, **kwargs)
        except (pika.exceptions.ConnectionClosed, pika.exceptions.ChannelClosed):
            logger.error('reconnecting to queue')
            self.connect()
            self._publish_model(*args, **kwargs)

    def _consume_xp(self):
        method, properties, body = next(self._xp_channel.consume(
            queue=self.EXPERIENCE_QUEUE_NAME,
            no_ack=False,
        ))
        self._xp_channel.basic_ack(delivery_tag=method.delivery_tag)
        return method, properties, body

    def consume_xp(self):
        try:
            return self._consume_xp()
        except (pika.exceptions.ConnectionClosed, pika.exceptions.ChannelClosed):
            logger.error('reconnecting to queue')
            self.connect()
            return self._consume_xp()

    def close(self):
        if self._conn and self._conn.is_open:
            logger.info('closing queue connection')
            self._conn.close()

class Experience:
    def __init__(self, game_id, states, actions, rewards, weight_version, team_id, seq_len):
        self.game_id = game_id
        self.weight_version = weight_version
        self.team_id = team_id
        self.seq_len = seq_len

        # TODO(tzaman): Like here, we need to calculate advantage before any padding or slicing.
        reward_sum = np.sum(rewards, axis=1)
        advantage = discount(x=reward_sum, gamma=0.98)

        # HACK: Slice to a standard length
        self.rewards = rewards[:self.seq_len, :]
        self.advantage = advantage[:self.seq_len]
        self.actions = actions[:self.seq_len, :]
        self.states = {key: None for key in Policy.INPUT_KEYS}
        for key in self.states:
            self.states[key] = states[key][:self.seq_len, :]

        # Calculate stuff
        self.total_reward = np.sum(self.rewards)

        # Create a vector with the n-hot mask of actions.
        self.vec_action_mask = self.actions.view(-1)

        # Count the amount of (multi-head) actions taken for each step.
        action_sum_per_step = torch.sum(self.actions, dim=1).view(-1).data.numpy()
        vec_rewards = np.ravel(self.advantage)  # flat view
        # Repeat the rewards where a step has multiple actions, the reward gets repeated.
        self.vec_mh_rewards = torch.from_numpy(np.repeat(vec_rewards, action_sum_per_step))

    def get_old_probs(self, policy):
        head_prob_dict, _ = policy.sequence(**self.states, hidden=None)
        flat_probs = policy.flatten_action_dict(head_prob_dict)
        vec_probs_all = flat_probs.view(-1)

        # Now mask the probs by the selection
        self.vec_old_probs = torch.masked_select(input=vec_probs_all, mask=self.vec_action_mask)
        self.vec_old_probs = self.vec_old_probs.detach()


def all_gather(t):
    _t = [torch.empty_like(t) for _ in range(dist.get_world_size())]
    dist.all_gather(_t, t)
    return torch.cat(_t)


class DotaOptimizer:

    MODEL_FILENAME_FMT = "model_%09d.pt"
    BUCKET_NAME = 'dotaservice'
    RUNNING_NORM_FACTOR = 0.95
    MODEL_HISTOGRAM_FREQ = 128
    MAX_GRAD_NORM = 0.5
    SPEED_KEY = 'steps per s'

    def __init__(self, rmq_host, rmq_port, epochs, seq_per_epoch, batch_size, seq_len,
                 learning_rate, checkpoint, pretrained_model, mq_prefetch_count, exp_dir, job_dir):
        super().__init__()
        self.rmq_host = rmq_host
        self.rmq_port = rmq_port
        self.epochs = epochs
        self.seq_per_epoch = seq_per_epoch
        self.batch_size = batch_size
        self.seq_len = seq_len
        self.learning_rate = learning_rate
        self.checkpoint = checkpoint
        self.mq_prefetch_count = mq_prefetch_count
        self.iteration_start = 0
        self.policy_base = Policy()
        self.exp_dir = exp_dir
        self.job_dir = job_dir
        self.log_dir = os.path.join(exp_dir, job_dir)
        self.iterations = 10000
        self.e_clip = 0.2

        if self.checkpoint:
            self.writer = SummaryWriter(log_dir=self.log_dir)
            logger.info('Checkpointing to: {}'.format(self.log_dir))
            client = storage.Client()
            self.bucket = client.get_bucket(self.BUCKET_NAME)

            # First, check if logdir exists.
            latest_model = self.get_latest_model(prefix=self.log_dir)
            # If there's a model in here, we resume from there
            if latest_model is not None:
                logger.info('Found a latest model in pretrained dir: {}'.format(latest_model))
                self.iteration_start = self.iteration_from_model_filename(filename=latest_model)
                if pretrained_model is not None:
                    logger.warning('Overriding pretrained model by latest model.')
                pretrained_model = latest_model

            if pretrained_model is not None:
                logger.info('Downloading: {}'.format(pretrained_model))
                model_blob = self.bucket.get_blob(pretrained_model)
                # TODO(tzaman): Download to BytesIO and supply to torch in that way.
                pretrained_model = '/tmp/model.pt'
                model_blob.download_to_filename(pretrained_model)

        if pretrained_model is not None:
            self.policy_base.load_state_dict(torch.load(pretrained_model), strict=False)

        if torch.distributed.is_available() and torch.distributed.is_initialized():
            self.policy = DistributedDataParallelSparseParamCPU(self.policy_base)
        else:
            self.policy = self.policy_base

        self.policy_old = copy.deepcopy(self.policy)

        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=self.learning_rate)
        self.time_last_step = time.time()

        self.mq = MessageQueue(host=self.rmq_host, port=self.rmq_port,
                               prefetch_count=mq_prefetch_count,
                               use_model_exchange=self.checkpoint)
        self.mq.connect()

    @staticmethod
    def iteration_from_model_filename(filename):
        x = re.search('(\d+)(?=.pt)', filename)
        return int(x.group(0))

    def get_latest_model(self, prefix):
        blobs = list(self.bucket.list_blobs(prefix=prefix))
        if not blobs:
            # Directory does not exist, or no files in directory.
            return None
        else:
            fns = [x.name for x in blobs if x.name[-3:] == '.pt']
            if not fns:
                # No relevant files in directory.
                return None
            fns.sort()
            latest_model = fns[-1]
            return latest_model

    @property
    def events_filename(self):
        return self.writer.file_writer.event_writer._ev_writer._file_name

    def optimize(self, probs, rewards):
        log_probs = torch.log(probs)
        loss = torch.mul(-log_probs, rewards)
        self.optimizer.zero_grad()
        loss = loss.mean()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.policy.parameters(), self.MAX_GRAD_NORM)
        self.optimizer.step()
        return loss

    def data_to_experience(self, data):
        return Experience(
            game_id=data['game_id'],
            states=data['states'],
            actions=data['actions'],
            rewards=data['rewards'],
            weight_version=data['weight_version'],
            team_id=data['team_id'],
            seq_len = self.seq_len
            )

    def run(self):
        assert self.seq_per_epoch >= self.batch_size
        assert self.seq_per_epoch % self.batch_size == 0

        for it in range(self.iteration_start, self.iterations):
            logger.info('iteration {}/{}'.format(it + 1, self.iterations))

            # First grab a bunch of experiences
            experiences = []
            rewards = []
            for s in range(self.seq_per_epoch):
                logger.debug(' adding experience {}/{}'.format(s + 1, self.seq_per_epoch))

                # Grab a rollout
                while True:
                    method, properties, body = self.mq.consume_xp()
                    data = pickle.loads(body)
                    l = data['actions'].size(0)
                    if  l >= self.seq_len:
                        break
                    else:
                        logger.warning('Skipping short sequence (length={})'.format(l))

                # TODO(tzaman): The rollout can consist out of multiple viable sequences.
                # These should be padded and then sliced into separate experiences.
                experience = self.data_to_experience(data)
                experience.get_old_probs(policy=self.policy_old)
                rewards.append(experience.total_reward)
                experiences.append(experience)

            assert len(experiences) % self.batch_size == 0

            losses = []
            for ep in range(self.epochs):
                logger.debug(' epoch {}/{}'.format(ep + 1, self.epochs))
                self.mq.process_data_events()

                # Shuffle the list of experience chunks.
                random.shuffle(experiences)

                # Divide into batches
                batches = [experiences[ib:ib + self.batch_size] for ib in range(0, len(experiences), self.batch_size)]
                for batch in batches:
                    losses.append(self.train(experiences=batch))
            
            # Set the new policy as the old one.
            self.policy_old.load_state_dict(self.policy.state_dict())

            losses = torch.stack(losses)
            loss = losses.mean()

            n_steps = self.seq_per_epoch * self.seq_len
            steps_per_s = n_steps / (time.time() - self.time_last_step)
            self.time_last_step = time.time()

            avg_weight_age = 0.  # TODO
            mean_reward = sum(rewards) / len(rewards)  # TODO

            metrics = {
                self.SPEED_KEY: steps_per_s,
                'mean_reward': mean_reward,
                'loss': loss,
            }

            logger.info('steps_per_s={:.2f}, avg_weight_age={:.2f}, mean_reward={:.2f}, loss={:.4f}'.format(
                steps_per_s, avg_weight_age, mean_reward, float(loss)))

            if self.checkpoint:
                # Write metrics to events file.
                for name, metric in metrics.items():
                    self.writer.add_scalar(name, metric, it)
                
                # Loss histogram
                self.writer.add_histogram('losses', losses, it)

                # Age histogram
                # self.writer.add_histogram('weight_age', weight_ages, it)

                # Rewards histogram
                # self.writer.add_histogram('rewards_radiant', reward_sums[teams==TEAM_RADIANT], it)
                # self.writer.add_histogram('rewards_dire', reward_sums[teams==TEAM_DIRE], it)

                # Model
                if it % self.MODEL_HISTOGRAM_FREQ == 1:
                    for name, param in self.policy_base.named_parameters():
                        self.writer.add_histogram(name, param.clone().cpu().data.numpy(), it)

                # RMQ Queue size.
                queue_size = self.mq.xp_queue_size
                if queue_size is not None:
                    self.writer.add_scalar('mq_size', queue_size, it)

                # Upload events to GCS
                self.writer.file_writer.flush()  # Flush before uploading
                blob = self.bucket.blob(self.events_filename)
                blob.upload_from_filename(filename=self.events_filename)

                self.upload_model(version=it)

    def train(self, experiences):
        # Train on one epoch of data.
        # Experiences is a list of (padded) experience chunks.
        logger.debug('train(experiences={})'.format(experiences))

        # Batch together all experiences.
        vec_mh_rewards = torch.cat([e.vec_mh_rewards for e in experiences])
        vec_action_mask = torch.cat([e.vec_action_mask for e in experiences])
        vec_old_probs = torch.cat([e.vec_old_probs for e in experiences])

        # TODO(tzaman): this normalizes takes into acount multi-heads too. We should use the
        # pre-calculated mean and eps scalars to normalize by, since we will be going over this
        # each piece of experience an 'episode' amount of times.
        vec_mh_rewards = normalize(vec_mh_rewards)

        states = {key: [] for key in Policy.INPUT_KEYS}
        for e in experiences:
            for key in e.states:
                states[key].append(e.states[key])
        states = {key: torch.stack(states[key]) for key in states}


        head_prob_dict, _ = self.policy(**states, hidden=None)  # -> {heads: tensors}
        flat_probs = self.policy.flatten_action_dict(head_prob_dict)
        vec_probs_all = flat_probs.view(-1)

        # Now mask the probs by the selection
        vec_probs = torch.masked_select(input=vec_probs_all, mask=vec_action_mask)

        # Probability ratio
        rt = vec_probs / (vec_old_probs + eps)

        # PPO Objective
        surr1 = rt * vec_mh_rewards
        surr2 = torch.clamp(rt, min=1.0 - self.e_clip, max=1.0 + self.e_clip) * vec_mh_rewards
        loss = -torch.min(surr1, surr2).mean()

        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.policy.parameters(), self.MAX_GRAD_NORM)
        self.optimizer.step()
        return loss




    def _unused(self, it):

        # Metrics
        reward_counter = Counter()
        teams = []
        weight_ages = []
        reward_sums = []
        losses = []

        # Add some experiences to the
        # experiences = []
        # for s in range(self.seq_per_epoch):
        #     logger.debug(' adding experience {}/{}'.format(s + 1, self.seq_per_epoch))
        #     method, properties, body = self.mq.consume_xp()
        #     data = pickle.loads(body)
        #     experience = self.data_to_experience(data)

        #     # Metrics
        #     experience.update_reward_counter(c=reward_counter)
        #     reward_sums.append(experience.total_reward)
        #     teams.append(experience.team_id)
        #     weight_ages.append(it - experience.weight_version)

        #     # Add to dequeue.
        #     experiences.append(experience)  
            
        # Set the original policy (that we're not updating)
        self.policy_old.load_state_dict(self.policy.state_dict())

        # Go over each epoch
        n_steps = 0
        n_batches = 0
        for e in range(self.epochs):
            self.policy.zero_grad()
            self.mq.process_data_events()
            logger.debug(' epoch {}/{}'.format(e + 1, self.epochs))
            # TODO: Shuffle this epoch
            indices = list(range(len(experiences)))
            random.shuffle(indices)
            steps_per_epoch =  len(experiences) // self.batch_size
            n_batches += steps_per_epoch
            for b in range(steps_per_epoch):
                logger.debug('  batch {}/{}'.format(b + 1, steps_per_epoch))
                start_index = b * self.batch_size
                batch = [experiences[i] for i in indices[start_index:start_index + self.batch_size]]
                n_steps += sum([e.steps for e in batch])

                # Normalize rewards
                rewards = [experience.mh_rewards for experience in batch]
                rewards = torch.cat(rewards)
                rewards = self.normalize(t=rewards)

                # Get original probabilities
                probs_old = torch.cat([experience.probs(policy=self.policy_old) for experience in batch])
                probs_old.detach()

                # Get new probabilities
                probs = torch.cat([experience.probs(policy=self.policy) for experience in batch])

                # Probability ratio
                rt = probs / (probs_old + eps)

                # PPO Objective
                surr1 = rt * rewards
                surr2 = torch.clamp(rt, min=1.0 - self.e_clip, max=1.0 + self.e_clip) * rewards
                loss = -torch.min(surr1, surr2).mean()

                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.policy.parameters(), self.MAX_GRAD_NORM)
                self.optimizer.step()

                losses.append(loss)

        # Metrics

        steps_per_s = n_steps / (time.time() - self.time_last_step)
        self.time_last_step = time.time()

        avg_weight_age = sum(weight_ages) / len(weight_ages)

        reward_counter = dict(reward_counter)

        reward_sum = sum(reward_counter.values())
        mean_reward = reward_sum / self.seq_per_epoch

        losses = torch.stack(losses)
        loss = losses.mean()
        logger.info('steps_per_s={:.2f}, avg_weight_age={:.2f}, mean_reward={:.2f}, loss={:.4f}'.format(
            steps_per_s, avg_weight_age, mean_reward, float(loss)))

        speed_key = 'steps per s'
        metrics = {
            'steps/batch': n_steps / n_batches,
            speed_key: steps_per_s,
            'mean_reward': mean_reward,
            'loss': loss,
        }
        for k, v in reward_counter.items():
            metrics['reward_{}'.format(k)] = v / self.seq_per_epoch

        # Reduce all the metrics
        metrics_t = torch.tensor(list(metrics.values()), dtype=torch.float32)

        weight_ages = torch.tensor(weight_ages)
        teams = torch.tensor(teams)
        reward_sums = torch.tensor(reward_sums)
        if is_distributed():
            dist.all_reduce(metrics_t, op=dist.ReduceOp.SUM)
            metrics_t /= dist.get_world_size()

            weight_ages = all_gather(weight_ages)
            teams = all_gather(teams)
            reward_sums = all_gather(reward_sums)

        metrics_d = dict(zip(metrics.keys(), metrics_t))

        if is_distributed():
            # Speed is always the sum.
            metrics_d[speed_key] *= dist.get_world_size()

        if self.checkpoint:
            # Write metrics to events file.
            for name, metric in metrics_d.items():
                self.writer.add_scalar(name, metric, it)
            
            # Loss histogram
            self.writer.add_histogram('losses', losses, it)

            # Age histogram
            self.writer.add_histogram('weight_age', weight_ages, it)

            # Rewards histogram
            self.writer.add_histogram('rewards_radiant', reward_sums[teams==TEAM_RADIANT], it)
            self.writer.add_histogram('rewards_dire', reward_sums[teams==TEAM_DIRE], it)

            # Model
            if it % self.MODEL_HISTOGRAM_FREQ == 1:
                for name, param in self.policy_base.named_parameters():
                    self.writer.add_histogram(name, param.clone().cpu().data.numpy(), it)

            # RMQ Queue size.
            queue_size = self.mq.xp_queue_size
            if queue_size is not None:
                self.writer.add_scalar('mq_size', queue_size, it)

            # Upload events to GCS
            self.writer.file_writer.flush()  # Flush before uploading
            blob = self.bucket.blob(self.events_filename)
            blob.upload_from_filename(filename=self.events_filename)

            self.upload_model(version=it)


    def upload_model(self, version):
        if not is_master():
            # Only rank 0 uploads the model.
            return

        filename = self.MODEL_FILENAME_FMT % version
        rel_path = os.path.join(self.log_dir, filename)

        # Serialize the model.
        buffer = io.BytesIO()
        state_dict = self.policy_base.state_dict()
        torch.save(obj=state_dict, f=buffer)
        state_dict_b = buffer.getvalue()

        # Write model to file.
        with open(rel_path, 'wb') as f:
            f.write(state_dict_b)

        # Send to exchange.
        self.mq.publish_model(msg=state_dict_b, hdr={'version': version})

        # Upload to GCP.
        blob = self.bucket.blob(rel_path)
        blob.upload_from_string(data=state_dict_b)  # Model


def init_distribution(backend='gloo'):
    logger.info('init_distribution')
    assert 'WORLD_SIZE' in os.environ
    if int(os.environ['WORLD_SIZE']) < 2:
        return
    torch.distributed.init_process_group(backend=backend)
    logger.info("Distribution initialized.")


def main(rmq_host, rmq_port, epochs, seq_per_epoch, batch_size, seq_len, learning_rate,
         pretrained_model, mq_prefetch_count, exp_dir, job_dir):
    logger.info('main(rmq_host={}, rmq_port={}, epochs={} seq_per_epoch={}, batch_size={},'
                ' seq_len={} learning_rate={}, pretrained_model={}, mq_prefetch_count={})'.format(
        rmq_host, rmq_port, epochs, seq_per_epoch, batch_size, seq_len, learning_rate, pretrained_model, mq_prefetch_count))

    # If applicable, initialize distributed training.
    if torch.distributed.is_available():
        init_distribution()
    else:
        logger.info('distribution unavailable')

    # Only the master should checkpoint.
    checkpoint = is_master()

    dota_optimizer = DotaOptimizer(
        rmq_host=rmq_host,
        rmq_port=rmq_port,
        epochs=epochs,
        seq_per_epoch=seq_per_epoch,
        batch_size=batch_size,
        seq_len=seq_len,
        learning_rate=learning_rate,
        checkpoint=checkpoint,
        pretrained_model=pretrained_model,
        mq_prefetch_count=mq_prefetch_count,
        exp_dir=exp_dir,
        job_dir=job_dir,
    )

    # Upload initial model.
    dota_optimizer.upload_model(version=0)

    dota_optimizer.run()


def default_job_dir():
    return '{}_{}'.format(datetime.now().strftime('%b%d_%H-%M-%S'), socket.gethostname())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--exp-dir", type=str, help="experiment dir name", default='runs')
    parser.add_argument("--job-dir", type=str, help="job dir name", default=default_job_dir())
    parser.add_argument("--ip", type=str, help="mq ip", default='127.0.0.1')
    parser.add_argument("--port", type=int, help="mq port", default=5672)
    parser.add_argument("--epochs", type=int, help="amount of epochs", default=4)
    parser.add_argument("--seq-per-epoch", type=int, help="amount of sequences per epoch", default=16)
    parser.add_argument("--batch-size", type=int, help="batch size", default=4)
    parser.add_argument("--seq-len", type=int, help="sequence length (as one sample in a minibatch)", default=256)
    parser.add_argument("--learning-rate", type=float, help="learning rate", default=1e-4)
    parser.add_argument("--pretrained-model", type=str, help="pretrained model file within gcs bucket", default=None)
    parser.add_argument("--mq-prefetch-count", type=int,
                        help="amount of experience messages to prefetch from mq", default=4)
    parser.add_argument("-l", "--log", dest="log_level", help="Set the logging level",
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='INFO')

    args = parser.parse_args()

    logger.setLevel(args.log_level)

    try:
        main(
            rmq_host=args.ip,
            rmq_port=args.port,
            epochs=args.epochs,
            seq_per_epoch=args.seq_per_epoch,
            batch_size=args.batch_size,
            seq_len=args.seq_len,
            learning_rate=args.learning_rate,
            pretrained_model=args.pretrained_model,
            mq_prefetch_count=args.mq_prefetch_count,
            exp_dir=args.exp_dir,
            job_dir=args.job_dir,
        )
    except KeyboardInterrupt:
        pass
