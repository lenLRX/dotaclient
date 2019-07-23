# DotaService

_This project is a WIP weekend-project._

DotaService exposes Dota 2 as a service. It provides an observe-act loop, to play in an object-oriented way.

This is very useful to provide an environment for reinforcement learning, and service aspect of it makes it
especially useful for distributed training. I am planning to provide a client python
module for this (`PyDota`) that mimics typical OpenAI gym APIs.

<div style="text-align:center">
<img src="dotaservice.png" alt="dotaservice connections" width="520"/>
</div>

---

# Notes

Create the protos

```sh
python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. protobuf/*.proto
```

Check open sockets:
```sh
$ lsof -n -i | grep -e LISTEN -e ESTABLISHED
>>> dota2     1061 tzaman  215u  IPv4 0x84b2d9c103958a77      0t0  TCP *:12120 (LISTEN)
```

DOTA comes with TensorFlow libs, primarily used for dota plus features:

```sh
$ cat Steam/steamapps/common/dota\ 2\ beta/game/dota/bin/linuxsteamrt64/libserver.so | grep -a tensorflow
>>> tf_server_client_connect_timeout_stf_server_client_read_timeout_stf_server_client_write_timeout_stf_server_stats_spew_interval_sdota_suggest_spew_pregame_itemsdota_suggest_spew_win_probabilitydota_suggest_spew_win_probability_chatdota_suggest_pregame_items_reductiondota_suggest_pregame_items_thresholddota_suggest_item_sequence_allow_thresholddota_suggest_item_sequence_threshold_startdota_suggest_item_sequence_threshold_fulldota_suggest_item_sequence_other_option_multiplierdota_suggest_item_sequence_dupe_multiplierdota_suggest_lane_trilane_penaltydota_suggest_win_probability_interval
```

Good command for dedicated bot 1v1
```sh
dota.sh \
-dedicated -insecure +map dota +sv_lan 1 +clientport 27006 +sv_cheats 1 \
-fill_with_bots -host_force_frametime_to_equal_tick_interval 1 \
-botworldstatetosocket_radiant 12120 -botworldstatetosocket_dire 12121 -botworldstatetosocket_frames 5 -botworldstatesocket_threaded \
+sv_hibernate_when_empty 0 +dota_auto_surrender_all_disconnected_timeout 180 +host_timescale 1 \
+dota_camera_edgemove 0
```

Clear dangling images.
```sh
docker rmi $(docker images -f dangling=true -q)
```

Create a 4GB Ramdisk on MacOS
```sh
diskutil erasevolume HFS+ 'ramdisk' `hdiutil attach -nomount ram://8388608`
```

Person that worked on the dota bot api and OpenAI's contact at Valve is _Chris Carollo_.

On the DOTA client, `clientport` default is `27015`. Multiple steam clients on same router/computer should
have different clienports; corresponding option e.g.: `+clientport 27017`.

Mid 1v1 mode skips the 30s strategy; `+dota_force_gamemode 21 +dota_1v1_skip_strategy 1`.

Saving replays is impossibe by dedicated servers: need SourceTV (tv_*).
27020 is default sourcetv port. clients can just conncet with `connect ip:27020` and drop into the game
```sh
# /root/Steam/steamapps/common/dota\ 2\ beta/game/dota.sh -dedicated +map dota +sv_lan 1 +sv_hibernate_when_empty 0 +dota_auto_surrender_all_disconnected_timeout 180 +tv_enable 1 +tv_autorecord 1 +tv_dota_auto_record_stressbots 1 +tv_delay 0 +dota_force_gamemode 11 +dota_force_upload_match_stats 1
```
Playing demo: `playdemo $demfile` looks in `dota 2 beta/game/dota` folder, not in `/replays`!
Or you just do `playdemo replays/$demfile` and it'll work too.
