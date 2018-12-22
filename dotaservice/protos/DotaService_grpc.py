# Generated by the Protocol Buffers compiler. DO NOT EDIT!
# source: dotaservice/protos/DotaService.proto
# plugin: grpclib.plugin.main
import abc

import grpclib.const
import grpclib.client

import dotaservice.protos.dota_gcmessages_common_bot_script_pb2
import dotaservice.protos.dota_shared_enums_pb2
import dotaservice.protos.DotaService_pb2


class DotaServiceBase(abc.ABC):

    @abc.abstractmethod
    async def reset(self, stream):
        pass

    @abc.abstractmethod
    async def step(self, stream):
        pass

    @abc.abstractmethod
    async def clear(self, stream):
        pass

    def __mapping__(self):
        return {
            '/DotaService/reset': grpclib.const.Handler(
                self.reset,
                grpclib.const.Cardinality.UNARY_UNARY,
                dotaservice.protos.DotaService_pb2.Config,
                dotaservice.protos.DotaService_pb2.Observation,
            ),
            '/DotaService/step': grpclib.const.Handler(
                self.step,
                grpclib.const.Cardinality.UNARY_UNARY,
                dotaservice.protos.DotaService_pb2.Actions,
                dotaservice.protos.DotaService_pb2.Observation,
            ),
            '/DotaService/clear': grpclib.const.Handler(
                self.clear,
                grpclib.const.Cardinality.UNARY_UNARY,
                dotaservice.protos.DotaService_pb2.Empty,
                dotaservice.protos.DotaService_pb2.Empty,
            ),
        }


class DotaServiceStub:

    def __init__(self, channel: grpclib.client.Channel) -> None:
        self.reset = grpclib.client.UnaryUnaryMethod(
            channel,
            '/DotaService/reset',
            dotaservice.protos.DotaService_pb2.Config,
            dotaservice.protos.DotaService_pb2.Observation,
        )
        self.step = grpclib.client.UnaryUnaryMethod(
            channel,
            '/DotaService/step',
            dotaservice.protos.DotaService_pb2.Actions,
            dotaservice.protos.DotaService_pb2.Observation,
        )
        self.clear = grpclib.client.UnaryUnaryMethod(
            channel,
            '/DotaService/clear',
            dotaservice.protos.DotaService_pb2.Empty,
            dotaservice.protos.DotaService_pb2.Empty,
        )
