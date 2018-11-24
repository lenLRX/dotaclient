# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: protobuf/DotaService.proto

import sys
_b=sys.version_info[0]<3 and (lambda x:x) or (lambda x:x.encode('latin1'))
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


from protobuf import CMsgBotWorldState_pb2 as protobuf_dot_CMsgBotWorldState__pb2
from protobuf import DotaAction_pb2 as protobuf_dot_DotaAction__pb2


DESCRIPTOR = _descriptor.FileDescriptor(
  name='protobuf/DotaService.proto',
  package='dotaservice',
  syntax='proto3',
  serialized_options=None,
  serialized_pb=_b('\n\x1aprotobuf/DotaService.proto\x12\x0b\x64otaservice\x1a protobuf/CMsgBotWorldState.proto\x1a\x19protobuf/DotaAction.proto\"%\n\x06\x41\x63tion\x12\x1b\n\x06\x61\x63tion\x18\x01 \x01(\x0b\x32\x0b.DotaAction\"6\n\x0bObservation\x12\'\n\x0bworld_state\x18\x01 \x01(\x0b\x32\x12.CMsgBotWorldState2F\n\x0b\x44otaService\x12\x37\n\x04Step\x12\x13.dotaservice.Action\x1a\x18.dotaservice.Observation\"\x00\x62\x06proto3')
  ,
  dependencies=[protobuf_dot_CMsgBotWorldState__pb2.DESCRIPTOR,protobuf_dot_DotaAction__pb2.DESCRIPTOR,])




_ACTION = _descriptor.Descriptor(
  name='Action',
  full_name='dotaservice.Action',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  fields=[
    _descriptor.FieldDescriptor(
      name='action', full_name='dotaservice.Action.action', index=0,
      number=1, type=11, cpp_type=10, label=1,
      has_default_value=False, default_value=None,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  serialized_options=None,
  is_extendable=False,
  syntax='proto3',
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=104,
  serialized_end=141,
)


_OBSERVATION = _descriptor.Descriptor(
  name='Observation',
  full_name='dotaservice.Observation',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  fields=[
    _descriptor.FieldDescriptor(
      name='world_state', full_name='dotaservice.Observation.world_state', index=0,
      number=1, type=11, cpp_type=10, label=1,
      has_default_value=False, default_value=None,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  serialized_options=None,
  is_extendable=False,
  syntax='proto3',
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=143,
  serialized_end=197,
)

_ACTION.fields_by_name['action'].message_type = protobuf_dot_DotaAction__pb2._DOTAACTION
_OBSERVATION.fields_by_name['world_state'].message_type = protobuf_dot_CMsgBotWorldState__pb2._CMSGBOTWORLDSTATE
DESCRIPTOR.message_types_by_name['Action'] = _ACTION
DESCRIPTOR.message_types_by_name['Observation'] = _OBSERVATION
_sym_db.RegisterFileDescriptor(DESCRIPTOR)

Action = _reflection.GeneratedProtocolMessageType('Action', (_message.Message,), dict(
  DESCRIPTOR = _ACTION,
  __module__ = 'protobuf.DotaService_pb2'
  # @@protoc_insertion_point(class_scope:dotaservice.Action)
  ))
_sym_db.RegisterMessage(Action)

Observation = _reflection.GeneratedProtocolMessageType('Observation', (_message.Message,), dict(
  DESCRIPTOR = _OBSERVATION,
  __module__ = 'protobuf.DotaService_pb2'
  # @@protoc_insertion_point(class_scope:dotaservice.Observation)
  ))
_sym_db.RegisterMessage(Observation)



_DOTASERVICE = _descriptor.ServiceDescriptor(
  name='DotaService',
  full_name='dotaservice.DotaService',
  file=DESCRIPTOR,
  index=0,
  serialized_options=None,
  serialized_start=199,
  serialized_end=269,
  methods=[
  _descriptor.MethodDescriptor(
    name='Step',
    full_name='dotaservice.DotaService.Step',
    index=0,
    containing_service=None,
    input_type=_ACTION,
    output_type=_OBSERVATION,
    serialized_options=None,
  ),
])
_sym_db.RegisterServiceDescriptor(_DOTASERVICE)

DESCRIPTOR.services_by_name['DotaService'] = _DOTASERVICE

# @@protoc_insertion_point(module_scope)
