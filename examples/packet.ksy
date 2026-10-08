meta:
  id: packet
  endian: le
  bit-endian: le
  encoding: UTF-8
seq:
  - id: header
    type: packet__header
  - id: payload
    type: u1
    repeat: expr
    repeat-expr: 4
types:
  packet__header:
    seq:
      - id: kind
        type: u1
      - id: length
        type: u2
