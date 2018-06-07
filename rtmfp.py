#!/usr/bin/env python
# (c) 2011, Cumulus Python <cumulus.python@gmail.com>. No rights reserved.
# Experimental rendezvous server for RTMFP in pure Python.
#
# This is a re-write of OpenRTMFP's Cumulus project from C++ to Python to fit with rtmplite project architecture.
# The original Cumulus project is in C++ and allows rendezvous and man-in-middle mode at the server.
# You can download the original project from https://github.com/OpenRTMFP/Cumulus, and compile and start on Mac OS X as follows:
#  $ cd CumulusLib; make -f Makefile-darwin clean; make -f Makefile-darwin
#  $ cd ../CumulusService; make -f Makefile-darwin
#  $ ./CumulusService -l8 -d all
#
# To get started with this rtmfp.py experiments, start it first in debug mode.
#  $ export PYTHONPATH=.:/path/to/p2p-sip/src:/path/to/PyCrypto
#  $ ./rtmfp.py -d --no-rtmp
# Then compile the test Flash application by editing testP2P/Makefile to supply the path for your mxmlc.
#  $ cd testP2P; make; cd ..
# Alternatively use the supplied testP2P.swf.
# Launch your web browser to open the file testP2P/bin-debug/testP2P.swf
#
# For p2p-mode: first click on publisher connect and then on player connect to see the video stream going.
#
# For man-in-middle mode: start rtmfp.py with --middle argument.
#  $ ./rtmfp.py -d --no-rtmp --middle
# Then click on publisher connect, copy the replacement peer id from the console of rtmfp.py and paste to the
# nearID/farID box in the browser, and finally click on the player connect button to see the video stream
# flowing via your server.
#
# For server connection mode instead of the direct (p2p) mode, start rtmfp.py without --middle argument, and
# then before clicking on publisher connect, uncheck the "direct" checkbox to enable FMS_CONNECTION mode in NetStream
# instead of DIRECT_CONNECTION.
#
# TODO: the server connection mode is not implemented yet.
# TODO: the interoperability with SIP is not implemented yet.
# TODO: the NAT traversal is not tested yet.

'''
This is a simple RTMFP rendezvous server to enable end-to-end and client-server UDP based media transport between Flash Player instances
and with this server.

Protocol Description
--------------------
(The description is based on the original OpenRTMFP's Cumulus project as well as http://www.ietf.org/proceedings/10mar/slides/tsvarea-1.pdf)


Session

An RTMFP session is an end-to-end bi-directional pipe between two UDP transport addresses. A transport address contains an IP address and port number, e.g.,
"192.1.2.3:1935". A session can have one or more flows where a flow is a logical path from one entity to another via zero or more intermediate entities. UDP
packets containing encrypted RTMFP data are exchanged in a session. A packet contains one or more messages. A packet is always encrypted using AES with 128-bit
keys.

In the protocol description below, all numbers are in network byte order (big-endian). The | operator indicates concatenation of data. The numbers are assumed
to be unsigned unless mentioned explicitly.


Scrambled Session ID

The packet format is as follows. Each packet has the first 32 bits of scrambled session-id followed by encrypted part. The scrambled (instead of raw) session-id
makes it difficult if not impossible to mangle packets by middle boxes such as NATs and layer-4 packet inspectors. The bit-wise XOR operator is used to scramble
the first 32-bit number with subsequent two 32-bit numbers. The XOR operator makes it possible to easily unscramble.

  packet := scrambled-session-id | encrypted-part

To scramble a session-id,

  scrambled-session-id = a^b^c

where ^ is the bit-wise XOR operator, a is session-id, and b and c are two 32-bit numbers from the first 8 bytes of the encrypted-part.

To unscramble,

  session-id = x^y^z

where z is the scrambled-session-id, and b and c are two 32-bit numbers from the first 8 bytes of the encrypted-part.

The session-id determines which session keys are used for encryption and decryption of the encrypted part. There is one exception for the fourth message in the
handshake which contains the non-zero session-id but the handshake (symmetric) session keys are used for encryption/decryption. For the handshake messages, a
symmetric AES (advanced encryption standard) with 128-bit (16 bytes) key of "Adobe Systems 02" (without quotes) is used. For subsequent in-session messages the
established asymmetric session keys are used as described later.


Encryption

Assuming that the AES keys are known, the encryption and decryption of the encrypted-part is done as follows. For decryption, an initialization vector of all
zeros (0's) is used for every decryption operation. For encryption, the raw-part is assumed to be padded as described later, and an initialization vector of all
zeros (0's) is used for every encryption operation. The decryption operation does not add additional padding, and the byte-size of the encrypted-part and the
raw-part must be same.

The decrypted raw-part format is as follows. It starts with a 16-bit checksum, followed by variable bytes of network-layer data, followed by padding. The
network-layer data ignores the padding for convenience.

  raw-part := checksum | network-layer-data | padding

The padding is a sequence of zero or more bytes where each byte is \xff. Since it uses 128-bit (16 bytes) key, padding ensures that the size in bytes of the
decrypted part is a multiple of 16. Thus, the size of padding is always less than 16 bytes and is calculated as follows:

  len(padding) = 16*N - len(network-layer-data) - 1
  where N is any positive number to make 0 <= padding-size < 16

For example, if network-layer-data is 84 bytes, then padding is 16*6-84-1=11 bytes. Adding a padding of 11 bytes makes the decrypted raw-part of size 96 which
is a multiple of 16 (bytes) hence works with AES with 128-bit key.


Checksum

The checksum is calculated over the concatenation of network-layer-data and padding. Thus for the encoding direction you should apply the padding followed by
checksum calculation and then AES encrypt, and for the decoding direction you should AES decrypt, verify checksum and then remove the (optional) padding if
needed. Usually padding removal is not needed because network-layer data decoders will ignore the remaining data anyway.

The 16-bit checksum number is calculated as follows. The concatenation of network-layer-data and padding is treated as a sequence of 16-bit numbers. If the size
in bytes is not an even number, i.e., not divisible by 2, then the last 16-bit number used in the checksum calculation has that last byte in the least-significant
position (weird!). All the 16-bit numbers are added in to a 32-bit number. The first 16-bit and last 16-bit numbers are again added, and the resulting number's
first 16 bits are added to itself. Only the least-significant 16 bit part of the resulting sum is used as the checksum.


Network Layer Data

The network-layer data contains flags, optional timestamp, optional timestamp echo and one or more chunks.

  network-layer-data = flags | timestamp | timestamp-echo | chunks ...

The flags value is a single byte containing these information: time-critical forward notification, time-critical reverse notification, whether timestamp is
present? whether timestamp echo is present and initiator/responder marker. The initiator/responder marker is useful if the symmetric (handshake) session keys
are used for AES, so that it protects against packet loopback to sender.

The bit format of the flags is not clear, but the following applies. For the handshake messages, the flags is \x0b. When the flags' least-significant 4-bits
are 1101b then the timestamp-echo is present. The timestamp seems to be always present. For in-session messages, the last 4-bits are either 1101b or 1001b.
--------------------------------------------------------------------
 flags      meaning
--------------------------------------------------------------------
 0000 1011  setup/handshake
 0100 1010  in-session no timestamp-echo (server to Flash Player)
 0100 1110  in-session with timestamp-echo (server to Flash Player)
 xxxx 1001  in-session no timestamp-echo (Flash Player to server)
 xxxx 1101  in-session with timestamp-echo (Flash Player to server)
--------------------------------------------------------------------

TODO: looks like bit \x04 indicates whether timestamp-echo is present. Probably \x80 indicates whether timestamp is present. last two bits of 11b indicates
handshake, 10b indicates server to client and 01b indicates client to server.

The timestamp is a 16-bit number that represents the time with 4 millisecond clock. The wall clock time can be used for generation of this timestamp value.
For example if the current time in seconds is tm = 1319571285.9947701 then timestamp is calculated as follows:

  int(time * 1000/4) & 0xffff = 46586

, i.e., assuming 4-millisecond clock, calculate the clock units and use the least significant 16-bits.

The timestamp-echo is just the timestamp value that was received in the incoming request and is being echo'ed back. The timestamp and its echo allows the
system to calculate the round-trip-time (RTT) and keep it up-to-date.

Each chunk starts with an 8-bit type, followed by the 16-bit size of payload, followed by the payload of size bytes. Note that \xff is reserved and not used for
chunk-type. This is useful in detecting when the network-layer-data has finished and padding has started because padding uses \xff. Alternatively, \x00 can also
be used for padding as that is reserved type too!

  chunk = type | size | payload


Message Flow

There are three types of session messages: session setup, control and flows. The session setup is part of the four-way handshake whereas control and flows are
in-session messages. The session setup contains initiator hello, responder hello, initiator initial keying, responder initial keying, responder hello cookie
change and responder redirect. The control messages are ping, ping reply, re-keying initiate, re-keying response, close, close acknowledge, forwarded initiator
hello. The flow messages are user data, next user data, buffer probe, user data ack (bitmap), user data ack (ranges) and flow exception report.

A new session starts with an handshake of the session setup. Under normal client-server case, the message flow is as follows:

 initiator (client)                target (server)
    |-------initiator hello---------->|
    |<------responder hello-----------|

Under peer-to-peer session setup case for NAT traversal, the server acts as a forwarder and forwards the hello to another connected client as follows:

 initiator (client)                forwarder (server)                     target (client)
    |-------initiator hello---------->|                                       |
    |                                 |---------- forwarded initiator hello-->|
    |                                 |<--------- ack ----------------------->|
    |<------------responder hello---------------------------------------------|

Alternatively, the server could redirect to another target by supplying an alternative list of target addresses as follows:

 initiator (client)                redirector (server)                     target (client)
    |-------initiator hello---------->|
    |<------responder redirect--------|
    |-------------initiator hello-------------------------------------------->|
    |<------------responder hello---------------------------------------------|

Note that the initiator, target, forwarder and redirector are just roles for session setup whereas client and server are specific implementations such as
Flash Player and Flash Media Server, respectively. Even a server may initiate an initiator hello to a client in which case the server becomes the initiator and
client becomes the target for that session. This mechanism is used for the man-in-middle mode in the Cumulus project.

The initiator hello may be forwarded to another target but the responder hello is sent directly. After that the initiator initial keying and the responder
initial keying are exchanged (between the initiator and the responded target directly) to establish the session keys for the session between the initiator
and the target. The four-way handshake prevents denial-of-service (DoS) via SYN-flooding and port scanning.

As mentioned before the handshake messages for session-setup use the symmetric AES key "Adobe Systems 02" (without the quotes), whereas in-session messages
use the established asymmetric AES keys. Intuitively, the session setup is sent over pre-established AES cryptosystem, and it creates new asymmetric AES
cryptosystem for the new session. Note that a session-id is established for the new session during the initial keying process, hence the first three messages
(initiator-hello, responder-hello and initiator-initial-keying) use session-id of 0, and the last responder-initial-keying uses the session-id sent by the
initiator in the previous message. This is further explained later.


Message Types

The 8-bit type values and their meaning are shown below.
---------------------------------
type  meaning
---------------------------------
\x30  initiator hello
\x70  responder hello
\x38  initiator initial keying
\x78  responder initial keying
\x0f  forwarded initiator hello
\x71  forwarded hello response

\x10  normal user data
\x11  next user data
\x0c  session failed on client side
\x4c  session died
\x01  causes response with \x41, reset keep alive
\x41  reset times keep alive
\x5e  negative ack
\x51  some ack
---------------------------------
TODO: most likely the bit \x01 indicates whether the transport-address is present or not.

The contents of the various message payloads are described below.


Variable Length Data

The protocol uses variable length data and variable length number. Any variable length data is usually prefixed by its size-in-bytes encoded as a variable
length number. A variable length number is an unsigned 28-bit number that is encoded in 1 to 4 bytes depending on its value. To get the bit-representation,
first assume the number to be composed of four 7-bit numbers as follows

  number = 0000dddd dddccccc ccbbbbbb baaaaaaa (in binary)
  where A=aaaaaaa, B=bbbbbbb, C=ccccccc, D=ddddddd are the four 7-bit numbers

The variable length number representation is as follows:

  0aaaaaaa (1 byte)  if B = C = D = 0
  0bbbbbbb 0aaaaaaa (2 bytes) if C = D = 0 and B != 0
  0ccccccc 0bbbbbbb 0aaaaaaa (3 bytes) if D = 0 and C != 0
  0ddddddd 0ccccccc 0bbbbbbb 0aaaaaaa (4 bytes) if D != 0

Thus a 28-bit number is represented as 1 to 4 bytes of variable length number. This mechanism saves bandwidth since most numbers are small and can fit in 1 or 2
bytes, but still allows values up to 2^28-1 in some cases.


Handshake

The initiator-hello payload contains an endpoint discriminator (EPD) and a tag. The payload format is as follows:

  initiator-hello payload = first | epd | tag

The first (8-bit) is unknown. The next epd is a variable length data that contains an epd-type (8-bit) and epd-value (remaining). Note that any variable length
data is prefixed by its length as a variable length number. The epd is typically less than 127 bytes, so only 8-bit length is enough. The tag is a fixed 128-bit
(16 bytes) randomly generated data. The fixed sized tag does not encode its length.
epd = epd-type | epd-value

The epd-type is \x0a for client-server and \x0f for peer-to-peer session. If epd-type is peer-to-peer, then the epd-value is peer-id whereas if epd-type is
client-server the epd-value is the RTMFP URL that the client uses to connect to. The initiator sets the epd-value such that the responder can tell whether the
initiator-hello is for them but an eavesdropper cannot deduce the identity from that epd. This is done, for example, using an one-way hash function of the
identity.

The tag is chosen randomly by the initiator, so that it can match the response against the pending session setup. Once the setup is complete the tag can be
forgotten.

When the target receives the initiator-hello, it checks whether the epd is for this endpoint. If it is for "another" endpoint, the initiator-hello is silently
discarded to avoid port scanning. If the target is an introducer (server) then it can respond with an responder, or redirect/proxy the message with
forwarded-initiator-hello to the actual target. In the general case, the target responds with responder-hello.

The responder-hello payload contains the tag echo, a new cookie and the responder certificate. The payload format is as follows:

  responder-hello payload = tag-echo | cookie | responder-certificate

The tag echo is same as the original tag from the initiator-hello but encoded as variable length data with variable length size. Since the tag is 16 bytes, size
can fit in 8-bits.

The cookie is a randomly and statelessly generated variable length data that can be used by the responder to only accept the next message if this message was
actually received by the initiator. This eliminates the "SYN flood" attacks, e.g., if a server had to store the initial state then an attacker can overload the
state memory slots by flooding with bogus initiator-hello and prevent further legitimate initiator-hello messages. The SYN flooding attack is common in TCP
servers. The length of the cookie is 64 bytes, but stored as a variable length data.

The responder certificate is also a variable length data containing some opaque data that is understood by the higher level crypto system of the application. In
this application, it uses the diffie-hellman (DH) secure key exchange as the crypto system.

Note that multiple EPD might map to the single endpoint, and the endpoint has single certificate. A server that does not care about the man-in-middle attack or
does not create secure EPD can generate random certificate to be returned as the responder certificate.

  certificate = \x01\x0A\x41\x0E | dh-public-num | \x02\x15\x02\x02\x15\x05\x02\x15\x0E

Here the dh-public-num is a 64-byte random number used for DH secure key exchange.

The initiator does not open another session to the same target identified by the responder certificate. If it detects that it already has an open session with
the target it moves the new flow requests to the existing open session and stops opening the new session. The responder has not stored any state so does not
need to care. (In our implementation we do store the initial state for simplicity, which may change later). This is one of the reason why the API is flow-based
rather than session-based, and session is implicitly handled at the lower layer.

If the initiator wants to continue opening the session, it sends the initiator-initial-keying message. The payload is as follows:

  initiator-initial-keying payload = initiator-session-id | cookie-echo | initiator-certificate | initiator-component | 'X'

Note that the payload is terminated by \x58 (or 'X' character).

The initiator picks a new session-id (32-bit number) to identify this new session, and uses it to demultiplex subsequent received packet. The responder uses this
initiator-session-id as the session-id to format the scrambled session-id in the packet sent in this session.

The cookie-echo is the same variable length data that was received in the responder-hello message. This allows the responder to relate this message with the
previous responder-hello message. The responder will process this message only if it thinks that the cookie-echo is valid. If the responder thinks that the
cookie-echo is valid except that the source address has changed since the cookie was generated it sends a cookie change message to the initiator.

In this DH crypto system, p and g are publicly known. In particular, g is 2, and p is a 1024-bit number. The initiator picks a new random 1024-bit DH private
number (x1) and generates 1024-bit DH public number (y1) as follows.

  y1 = g ^ x1 % p


The initiator-certificate is understood by the crypto system and contains the initiator's DH public number (y1) in the last 128 bytes.

The initiator-component is understood by the crypto system and contains an initiator-nonce to be used in DH algorithm as described later.

When the target receives this message, it generates a new random 1024-bit DH private number (x2) and generates 1024-bit DH public number (y2) as follows.

  y2 = g ^ x2 % p

Now that the target knows the initiator's DH public number (y1) and it generates the 1024-bit DH shared secret as follows.

  shared-secret = y1 ^ x2 % p

The target generates a responder-nonce to be sent back to the initiator. The responder-nonce is as follows.

  responder-nonce = \x03\x1A\x00\x00\x02\x1E\x00\x81\x02\x0D\x02 | responder's DH public number

The peer-id is the 256-bit SHA256 (hash) of the certificate. At this time the responder knows the peer-id of the initiator from the initiator-certificate.

The target picks a new 32-bit responder's session-id number to demultiplex subsequent packet for this session. At this time the server creates a new session
context to identify the new session. It also generates asymmetric AES keys to be used for this session using the shared-secret and the initiator and responder
nonces as follows.

  decode key = HMAC-SHA256(shared-secret, HMAC-SHA256(responder nonce, initiator nonce))[:16]
  encode key = HMAC-SHA256(shared-secret, HMAC-SHA256(initiator nonce, responder nonce))[:16]

The decode key is used by the target to AES decode incoming packet containing this responder's session-id. The encode key is used by the target to AES encode
outgoing packet to the initiator's session-id. Only the first 16 bytes (128-bits) are used as the actual AES encode and decode keys.

The target sends the responder-initial-keying message back to the initiator. The payload is as follows.

  responder-initial-keying payload = responder session-id | responder's nonce | 'X'

Note that the payload is terminated by \x58 (or 'X' character). Note also that this handshake response is encrypted using the symmetric (handshake) AES key
instead of the newly generated asymmetric keys.

When the initiator receives this message it also calculates the AES keys for this session.

  encode key = HMAC-SHA256(shared-secret, HMAC-SHA256(responder nonce, initiator nonce))[:16]
  decode key = HMAC-SHA256(shared-secret, HMAC-SHA256(initiator nonce, responder nonce))[:16]

As before, only the first 16 bytes (128-bits) are used as the AES keys. The encode key of initiator is same as the decode key of the responder and the decode
key of the initiator is same as the encode key of the responder.

When a server acts as a forwarder, it receives an incoming initiator-hello and sends a forwarded-initiator-hello in an existing session to the target. The
payload is follows.

  forwarded initiator hello payload := first | epd | transport-address | tag

The first 8-bit value is \x22. The epd value is same as that in the initiator-hello -- a variable length data containing epd-type and epd-value. The epd-type
is \x0f for a peer-to-peer session. The epd-value is the target peer-id that was received as epd-value in the initiator-hello.

The tag is echoed from the incoming initiator-hello and is a fixed 16 bytes value.

The transport address contains a flag for indicating whether the address is private or public, the binary bits of IP address and optional port number. The
transport address is that of the initiator as known to the forwarder.

  transport-address := flag | ip-address | port-number

The flag is an 8-bit number with the first most significant bit as 1 if the port-number is present, otherwise 0. The least significant two bits are 10b for
public IP address and 01b for private IP address.

The ip-address is either 4-bytes (IPv4) or 16-bytes (IPv6) binary representation of the IP address.

The optional port-number is 16-bit number and is present when the flag indicates so.

The server then sends a forwarded-hello-response message back to the initiator with the transport-address of the target.

  forwarded-hello-response = transport-address | transport-address | ...

The payload is basically one or more transport addresses of the intended target, with the public address first.

After this the initiator client directly sends subsequent messages to the responder, and vice-versa.

A normal-user-data message type is used to deal with any user data in the flows. The payload is shown below.

  normal-user-data payload := flags | flow-id | seq | forward-seq-offset | options | data

The flags, an 8-bits number, indicate fragmentation, options-present, abandon and/or final. Following table indicates the meaning of the bits from most
significant to least significant.

bit   meaning
0x80  options are present if set, otherwise absent
0x40
0x20  with beforepart
0x10  with afterpart
0x08
0x04
0x02  abandon
0x01  final

The flow-id, seq and forward-seq-offset are all variable length numbers. The flow-id is the flow identifier. The seq is the sequence number. The
forward-seq-offset is used for partially reliable in-order delivery.

The options are present only when the flags indicate so using the most significant bit as 1. The options are as follows.

TODO: define options

The subsequent data in the fragment may be sent using next-user-data message with the payload as follows:

  next-user-data := flags | data

This is just a compact form of the user data when multiple user data messages are sent in the same packet. The flow-id, seq and forward-seq-offset are implicit,
i.e., flow-id is same and subsequent next-user-data have incrementing seq and forward-seq-offset. Options are not present. A single packet never contains data
from more than one flow to avoid head-of-line blocking and to enable priority inversion in case of problems.


TODO

Fill in description of the remaining message flows beyond handshake.
Describe the man-in-middle mode that enables audio/video flowing through the server.
'''

import sys
import itertools
import urlparse
import re
import socket
import struct
import time
import random
import hmac
import hashlib
import logging
import multitask
import amf

try:
    from Crypto.Cipher import AES

    class AESEncrypt(object):
        def __init__(self, key):
            self.key = key[:16]
            self.iv = '\x00' * 16 # create null-IV

        def encode(self, data):
            self.cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
            result = self.cipher.encrypt(data)
            return result


    class AESDecrypt(object):
        def __init__(self, key):
            self.key = key[:16]
            self.iv = '\x00' * 16 # create null-IV

        def decode(self, data):
            self.cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
            result = self.cipher.decrypt(data)
            return result
except ImportError:
    logging.warn('Please install PyCrypto for faster performance. Falling back to Python aes.py which is *very* slow')
    import aes

    class AESEncrypt(object):
        def __init__(self, key):
            self.key = key[:16]
        def encode(self, data):
            return aes.encrypt(self.key, data, iv=aes.iv_null())

    class AESDecrypt(object):
        def __init__(self, key):
            self.key = key[:16]
        def decode(self, data):
            return aes.decrypt(self.key, data, iv=aes.iv_null()) # clip to original data length


#--------------------------------------
# GENERAL UTILITY
#--------------------------------------

def _isLocal(value):
    '''Check whether the supplied address tuple ("dotted-ip", port) is local loopback or not?'''
    return value[0] == '127.0.0.1'

def _str2address(value, hasPort=True):
    '''Parse the given IPv4 or IPv6 address in to ("dotted-ip", port). If port is False, do not parse port, and return it as 0.
    @param value the binary string representing ip (if hasPort is False) or ip plus port (if hasPort is True).
    @param hasPort if False, then value must not have port. It returns port as 0.

    >>> print _str2address('\x7f\x00\x00\x01\x00\x80')
    ('127.0.0.1', 128)
    '''
    if hasPort:
        if len(value)>=2:
            ip, port = (value[:-2], struct.unpack('>H', value[-2:])[0]) if hasPort else (value, 0)
        else:
            raise ValueError('invalid length of IP value ' + len(value))
    else:
        ip, port = value, 0
    if len(ip) == 4:
        return ('.'.join([ord(x) for x in ip]), port)
    elif len(ip) == 16:
        return (':'.join(['%X'%((ord(x) << 8 | ord(y)),) for x, y in zip(ip[::2], ip[1::2])]), port)
    else:
        raise ValueError('invalid length of IP value ' + len(value))

def _address2str(value, hasPort=True):
    '''Represent the given ("dotted-ip", port) in to binary string.
    @param value the tuple of length 2 of the form ('dotted-ip', port)
    @param hasPort if False, do not represent port in the returned string. The value must always have port.

    >>> print _address2str(('127.0.0.1', 128))
    \x7f\x00\x00\x01\x00\x80
    '''
    host, port = value
    if host.find(':') < 0: # IPv4
        parts = host.split('.')
        if len(parts) != 4:
            raise ValueError('invalid dotted-ip')
        ip = ''.join([chr(int(x, 10)) for x in parts])
    else: # IPv6
        parts = (host[1:-1] if host[0] == '[' and host[-1] == ']' else host).split(':')
        if len(parts) != 8:
            raise ValueError('invalid dotted-ipv6')
        ip = ''.join([struct.pack('>H', int(x, 16)) for x in parts])
    return (ip + struct.pack('>H', port)) if hasPort else ip

def _ipport2address(value):
    '''Parse a string of the form "dotted-ip:port" to ("dotted-ip", port).'''
    ip, _, port = value.rpartition(':')
    return (ip, int(port) if port else 0)

def _address2ipport(address, default_port=1935):
    return address[0] if address[1] in (0, default_port) else '%s:%d'%(address[0], address[1])

def _sizeLength7(value):
    '''Return the length of storing value using 7 bits variable integer.'''
    return 4 if value >= 0x200000 else 3 if value >= 0x4000 else 2 if value >= 0x80 else 1

def _packLength7(value):
    d, c, b, a = (value & 0x7F), ((value & 0x03f80) >> 7), ((value & 0x1fc000) >> 14), ((value & 0x0fe00000) >> 21)
    return (chr(0x80 | a) if a else '') + (chr(0x80 | b) if a or b else '') + (chr(0x80 | c) if a or b or c else '') + chr(d)


def _unpackLength7(data): # return (value, remaining)
    value = index = 0
    while index < 4:
        byte = ord(data[index])
        value = (value << 7) | (byte & 0x7f)
        index += 1
        if byte & 0x80 == 0: break
    return (value, data[index:])


def _packString(value, sizeLength=None):
    return (struct.pack('>H', len(value)) if sizeLength == 16 else struct.pack('>B', len(value)) if sizeLength == 8 else _packLength7(len(value))) + value


def _unpackString(data, sizeLength=None): # returns (value, remaining)
    if sizeLength == 16:
        length, data = struct.unpack('>H', data[:2])[0], data[2:]
    elif sizeLength == 8:
        length, data = struct.unpack('>B', data[:1])[0], data[1:]
    else:
        length, data = _unpackLength7(data)

    return data[:length], data[length:]


def _packAddress(value, publicFlag):
    return chr((0x02 if publicFlag else 0x01) | (0x80 if value[0].find(':') >= 0 else 0)) + _address2str(value)


def _url2pathquery(value):
    '''Unpack an rtmfp URL to (path, dict) where dict is query parameters indexed by name, with value as list.'''
    url1 = urlparse.urlparse(value)
    url2 = urlparse.urlparse(re.sub('^' + url1.scheme, 'http', value))
    return (url2.path, urlparse.parse_qs(url2.query))


def truncate(data, size=16, pre=8, post=5):
    length, data = len(data), (data if len(data) <= size else data[:pre] + '...' + data[-post:])
    return '[%d] %r'%(length, data)


#--------------------------------------
# SECURITY
#--------------------------------------

_key = 'Adobe Systems 02'
_int2bin = lambda x, size: (''.join(chr(a) for a in [((x>>c)&0x0ff) for c in xrange((size-1)*8,-8,-8)])) if x is not None else '\x00'*size
_bin2int = lambda x: long(''.join('%02x'%(ord(a)) for a in x), 16)
_dh1024p = _bin2int('\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xC9\x0F\xDA\xA2\x21\x68\xC2\x34\xC4\xC6\x62\x8B\x80\xDC\x1C\xD1\x29\x02\x4E\x08\x8A\x67\xCC\x74\x02\x0B\xBE\xA6\x3B\x13\x9B\x22\x51\x4A\x08\x79\x8E\x34\x04\xDD\xEF\x95\x19\xB3\xCD\x3A\x43\x1B\x30\x2B\x0A\x6D\xF2\x5F\x14\x37\x4F\xE1\x35\x6D\x6D\x51\xC2\x45\xE4\x85\xB5\x76\x62\x5E\x7E\xC6\xF4\x4C\x42\xE9\xA6\x37\xED\x6B\x0B\xFF\x5C\xB6\xF4\x06\xB7\xED\xEE\x38\x6B\xFB\x5A\x89\x9F\xA5\xAE\x9F\x24\x11\x7C\x4B\x1F\xE6\x49\x28\x66\x51\xEC\xE6\x53\x81\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF')
_random = lambda size: ''.join([chr(random.randint(0, 255)) for i in xrange(size)])
_bin2hex = lambda data: ''.join(['%02x'%(ord(x),) for x in data])


def _checkSum(data):
    data, last = (data[:-1], ord(data[-1])) if len(data) % 2 != 0 else (data, 0)
    cs = reduce(lambda x,y: x+y, ((ord(x) << 8 | ord(y)) for x, y in itertools.izip(data[::2], data[1::2])), 0) + last
    cs = (cs >> 16) + (cs & 0xffff)
    cs += (cs >> 16)
    return (~cs) & 0xffff


def _decode(decoder, data):
    raw = data[:4] + decoder.decode(data[4:])
    if struct.unpack('>H', raw[4:6])[0] != _checkSum(raw[6:]):
        logging.debug('ERROR: decode() invalid checksum %x != %x data=%r'%(struct.unpack('>H', raw[4:6])[0], _checkSum(raw[6:]), raw[6:]))
        raise ValueError('invalid checksum')
    return raw


def _encode(encoder, data):
    plen = (0xffffffff - len(data) + 5) & 0x0f # 4-bytes header, plen = 16*N - len for some int N and 0 <= plen < 16 (128 bits)
    data += '\xff' * plen
    data = data[:4] + struct.pack('>H', _checkSum(data[6:])) + data[6:]
    return data[:4] + encoder.encode(data[4:])


def _unpackId(data):
    a, b, c = struct.unpack('>III', data[:12])
    return a^b^c


def _packId(data, farId):
    b, c = struct.unpack('>II', data[4:12])
    a = b^c^farId
    return struct.pack('>I', a) + data[4:]


def _beginDH():
    '''Using known p (1024bit prime) and g=2, return (x, y) where x=random private value, y=g^x mod p public value.'''
    g, x = 2, _bin2int(_random(128))
    return (x, pow(g, x, _dh1024p))


def _endDH(x, y):
    '''Using known p (1024bit prime), return secret=y^x mod p where x=random private value, y=other sides' public value.'''
    return pow(y, x, _dh1024p)


def _asymetricKeys(secret, initNonce, respNonce): # returns (dkey, ekey)
    return (hmac.new(secret, hmac.new(respNonce, initNonce, hashlib.sha256).digest(), hashlib.sha256).digest(), hmac.new(secret, hmac.new(initNonce, respNonce, hashlib.sha256).digest(), hashlib.sha256).digest())


#--------------------------------------
# DATA: Peer, Peers, Group, Client, Target, Cookie
#--------------------------------------

class Entity(object):
    def __init__(self):
        self.id = '\x00'*32 # 32 byte value

    def __cmp__(self, other):
        return cmp(self.id, other.id) if isinstance(other, Entity) else cmp(self.id, other)

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return '<%s id=%s/>'%(self.__class__.__name__, self.id and truncate(self.id))


class Client(Entity):
    def __init__(self):
        Entity.__init__(self)
        self.swfUrl = self.pageUrl = self.path = self.data = self.params = None

    def __repr__(self):
        return '<%s id=%s swfUrl=%r pageUrl=%r path=%r/>'%(self.__class__.__name__, self.id and truncate(self.id), self.swfUrl, self.pageUrl, self.path)


class Peer(Client):
    '''A single peer representation.

    @ivar address (tuple) the address of the form ('ip', port) where ip is dotted-string and port is int.
    @ivar privateAddress (list) the list of ('ip', port).
    @ivar state (str) one of 'none', 'accepted', 'rejected'.
    @ivar ping (float) ping round-trip-time in seconds to this Peer.
    @ivar groups (list) list of Group objects this Peer is part of.
    '''
    NONE, ACCEPTED, REJECTED = 'none', 'accepted', 'rejected' # peer state

    def __init__(self): # initialize the peer
        Client.__init__(self)
        self.address, self._privateAddress, self._ping, self.state, self.groups = None, [], 0, Peer.NONE, []

    def __repr__(self):
        return '<%s id=%s swfUrl=%r pageUrl=%r path=%r address=%r privateAddress=%r state=%r/>'%(self.__class__.__name__, self.id and truncate(self.id), self.swfUrl, self.pageUrl, self.path, self.address, self._privateAddress, self.state)

    def close(self): # unsubscribe groups when closing this peer
        for group in self.groups:
            group.peers.remove(self)
        self.groups[:] = []

    def dup(self):
        peer = Peer()
        peer.id, peer.swfUrl, peer.pageUrl, peer.path, peer.data = self.id, self.swfUrl, self.pageUrl, self.path, self.data # Entity, Client
        peer.address, peer._privateAddress, peer._ping, peer.state = self.address, self._privateAddress[:], self._ping, self.state # Peer
        return peer

    def _getPing(self):
        return self._ping

    def _setPing(self, value):
        self._ping = value
        for group in self.groups:
            group.peers.remove(self) # re-add so that sorted by ping time
            group.peers.add(self)

    ping = property(fget=_getPing, fset=_setPing)

    def _getPrivateAddress(self):
        return self._privateAddress

    def _setPrivateAddress(self, value):
        self._privateAddress[:] = [(x[0], x[1] or self.address[1]) for x in value]
    privateAddress = property(fget=_getPrivateAddress, fset=_setPrivateAddress)


class Peers(list):
    '''List of Peer objects kept sorted by ping property. Must use add() method to add to the list.'''
    def close(self):
        self[:] = []

    def add(self, peer):
        if peer not in self:
            for index, p in enumerate(self):
                if peer.ping >= p.ping:
                    break
            self.insert(index, peer)

    def best(self, asker, max_count=6):
        return ([x for x in self if not _isLocal(x.address) and x != asker] + [x for x in self if _isLocal(x.address) and x != asker])[:max_count]


class Group(object):
    '''A Group has a unique id and a list of peers.'''
    def __init__(self, gid):
        self.id, self.peers = gid, Peers()

    def __cmp__(self, other):
        return cmp(self.id, other.id if isinstance(other, Group) else other)

    def add(self, peer):
        if peer not in self.peers:
            peer.groups.append(self)
            self.peers.add(peer)

    def remove(self, peer):
        if peer in self.peers:
            peer.groups.remove(self)
            self.peers.remove(peer)


class Target(Entity):
    def __init__(self, address, cookie=None):
        Entity.__init__(self)
        self.address, self.isPeer = address, bool(cookie is not None)
        self.peerId = self.Kp = self.DH = None
        if not address[1]:
            address = (address[0], 1935)
        if cookie is not None:
            self.DH, cookie.DH, self.Kp = cookie.DH, None, cookie.nonce[11:11+128]
            cookie.nonce = cookie.nonce[:9] + '\x1d' + cookie.nonce[10:]
            self.id = hashlib.sha256(cookie.nonce[7:]).digest()
            cookie.nonce = cookie.nonce[:9] + '\x0d' + cookie.nonce[10:]

    def close(self):
        pass


class Cookie(object):
    def __init__(self, value):
        self.queryUrl, self.id, self.createdTs = '', 0, time.time()
        self.target = self.nonce = self.DH = None
        if isinstance(value, Target): # target
            self.target, self.DH = value, value.DH
            logging.debug('   create cookie with target %r'%(value,))
            self.nonce = '\x03\x1A\x00\x00\x02\x1E\x00\x41\x0E' + _random(64) # len is 9+64=73
        else: # queryUrl
            self.queryUrl = value
            self.DH = _beginDH()
            logging.debug('   create cookie with queryUrl %r'%(value,))
            self.nonce = '\x03\x1A\x00\x00\x02\x1E\x00\x81\x02\x0D\x02' + _int2bin(self.DH[1], 128) # len is 11+key

    def close(self):
        pass

    @property
    def obsolete(self):
        return (time.time() - self.createdTs) >= 120 # two minutes elapsed

    def computeKeys(self, initKey, initNonce): # returns (dkey, ekey)
        assert len(initKey) == 128
        sharedSecret = _int2bin(_endDH(self.DH[0], _bin2int(initKey)), len(initKey))
        assert len(sharedSecret) == 128
        # return _asymetricKeys(sharedSecret, initNonce, self.nonce)
        dkey, ekey = _asymetricKeys(sharedSecret, initNonce, self.nonce)
        logging.debug('   Cookie.computeKeys()\n     dkey=%s\n     ekey=%s'%(truncate(dkey), truncate(ekey)))
        return (dkey, ekey)

    def __repr__(self):
        return '<Cookie id=%r queryUrl=%r nonce=%s />'%(self.id, self.queryUrl, truncate(self.nonce))

    def __str__(self):
        return struct.pack('>I', self.id) + _packString(self.nonce) + struct.pack('>B', 0x58)


#--------------------------------------
# DATA: Stream, Flow, Packet, QoS
#--------------------------------------

class QoS(object):
    '''
    Quality of service statistics for each stream and media type.
    Each sample is tuple (time, received, lost) of three int values.
    '''
    def __init__(self):
        self.droppedFrames = self.lossRate = self.jitter = self.prevTime = self.reception = 0
        self.samples = []

    def add(self, tm, received, lost):
        now = time.time()
        if self.prevTime > 0 and tm >= self.prevTime:
            result = self.jitter + (now - self.reception) - (tm - self.prevTime)
            self.jitter = int(result if result > 0 else 0)
        self.reception, self.prevTime = time.time(), tm
        self.samples[:] = [s for s in self.samples if (s[0] >= now - 10)] + [(tm, received, lost)] # keep only last 10 seconds of samples
        total, lost = sum([s[1] for s in self.samples]), sum([s[2] for s in self.samples])
        if total != 0:
            self.lossRate = float(lost)/(total+lost)

    def close(self):
        self.droppedFrames = self.lossRate = self.jitter = self.prevTime = self.reception = 0
        self.samples[:] = []

    def reset(self):
        self.close()


class Publication(object):
    def __init__(self, name):
        self.publisherId, self.name, self._time, self._firstKeyFrame, self._listeners, self.videoQoS, self.audioQoS = 0, name, 0, False, {}, QoS(), QoS()

    def start(self, client, lid):
        # TODO: seems no use, but it is called by Streams.publish
        pass

    def close(self):
        for item in self._listeners.values():
            item.close()
        self._listeners.clear()

    def addListener(self, client, lid, writer, unbuffered):
        if lid in self._listeners:
            logging.debug('Publication.addListener() listener %r is already subscribed for publication %r'%(lid, self.publisherId))
        else:
            self._listeners[lid] = Listener(lid, self, writer, unbuffered)


class Streams(object):
    '''Collection of streams by numeric id.'''
    def __init__(self):
        self._nextId, self.publications, self._streams = 0, {}, [] # publications is str=>Publication, and _streams is set of numeric id, TODO: self._nextId => itertools.count(1) ?

    def create(self):
        while self._nextId == 0 or self._nextId in self._streams:
            self._nextId += 1
        self._streams.append(self._nextId)
        logging.debug('new stream %d'%(self._nextId,))
        return self._nextId

    def destroy(self, lid):
        logging.debug('delete stream %d' % lid)
        if lid in self._streams:
            self._streams.remove(lid)

    def publish(self, client, lid, name):
        pub = self.publications[name] = Publication(name)
        return pub.start(client, lid)

    def unpublish(self, client, lid, name):
        if name not in self.publications:
            logging.debug('the stream %s with a %u id does not exist, unpublish useless'%(name, lid))
            return
        pub = self.publications[name]
        pub.stop(client, lid)
        if pub.publisherId == 0 and len(pub._listeners) == 0:
            del self.publications[name]
            pub.close()

    def subscribe(self, client, lid, name, writer, start=-2000):
        pub = self.publications[name] = Publication(name)
        pub.addListener(client, lid, writer, start == -3000)

    def unsubscribe(self, client, lid, name):
        if name not in self.publications:
            logging.debug('the stream %s does not exist, unsubscribe useless'%(name,))
            return
        pub = self.publications[name]
        pub.removeListener(client, lid)
        if pub.publisherId == 0 and len(pub._listeners) == 0:
            del self.publications[name]
            pub.close()


class Packet(object):
    '''Has one or more data fragments. Use data to access combined data, and count for number of fragments.'''
    def __init__(self, data):
        self.data, self.count = data or '', 1
    def add(self, data):
        self.data += data; self.count += 1

class Fragment(object):
    '''Has data and flags.'''
    def __init__(self, data, flags):
        self.data, self.flags = data, flags


class Message(object):
    def __init__(self, repeatable, data=None, memAck=None):
        self.stream = amf.BytesIO(data) if data else amf.BytesIO()
        self._reader, self.fragments, self.startStage, self.repeatable = self.stream, [], 0, repeatable
        if memAck:
            self._bufferAck, self._memAck = memAck, amf.BytesIO(memAck)
        else:
            self.amfWriter = amf.AMF0(data=self.stream)

    def init(self, position):
        self.stream.seek(position)
        return self.stream.remaining() if not self.repeatable else self.stream.len

    def memAck(self):
        if self.repeatable:
            return self.reader()
        return self._memAck.remaining, self._reader

    def reader(self):
        return self.init(self.fragments and self.fragments[0] or 0), self._reader


# abstract flow class
class Flow(object):
    '''Flow serves as base class for individual flow type.

    @ivar id (int) flow identifier
    @ivar signature (str) security signature
    '''
    signature = None # undefined

    EMPTY, AUDIO, VIDEO, AMF_WITH_HANDLER, AMF = 0x00, 0x08, 0x09, 0x14, 0x0F
    HEADER, WITH_AFTERPART, WITH_BEFOREPART, ABANDONMENT, END = 0x80, 0x10, 0x20, 0x02, 0x01 # message


    def __init__(self, id_, signature, peer, server, session):
        self.id, self.peer, self.server, self.session = id_, peer, server, session
        self.error, self.packet, self.stage, self.completed, self.fragments, self.writer = None, None, 0, False, {}, FlowWriter(signature, session)
        if self.writer.flowId == 0:
            self.writer.flowId = id_

    def dup(self):
        f = Flow(self.id, self.signature, Peer(), self.server, self.session)
        f.stage, f.critical = self.stage, self.critical
        self.close()

    @property
    def count(self): # TODO: seems no use, need check
        return len(self.writer._messages)

    def close(self):
        if not self.completed and self.writer.signature:
            logging.debug('Flow.close() flow consumed: %r'%(self.id,))
        self.completed = True
        self.fragments.clear() # TODO: do we need to call close on values?
        self.packet = None
        self.writer.close()

    def fail(self, error):
        logging.debug('Flow.fail() flow failed: %r, %s' % (self.id, error))
        if not self.completed:
            self.session.writeMessage(0x5e, _packLength7(self.id) + '\x00')

    def unpack(self, data): # given data, return (type, remaining)
        if not data:
            return self.EMPTY
        type = ord(data[0])
        if type == 0x11:
            return (self.AMF_WITH_HANDLER, data[6:])
        elif type == self.AMF_WITH_HANDLER:
            return (self.AMF_WITH_HANDLER, data[5:])
        elif type == self.AMF:
            return (self.AMF, data[6:])
        elif type in (self.AUDIO, self.VIDEO, 0x01):
            return (type, data[1:])
        elif type == 0x04:
            return (type, data[5:])
        else:
            logging.debug('Flow.unpack() error in unpacking type 0x%02x'%(type,))
            return (type, data[1:])

    def commit(self):
        self.session.writeMessage(0x51, _packLength7(self.id) + chr(0x7f if self.writer.signature else 0x00) + _packLength7(self.stage))
        self.commitHandler()
        self.writer.flush()

    def fragmentHandler(self, stage, deltaNack, fragment, flags):
        if self.completed:
            return
        nextStage = self.stage + 1
        if stage < nextStage:
            logging.debug('Flow.fragmentHandler() stage %r on flow %r has already been received'%(stage, self.id))
            return
        if deltaNack > stage or deltaNack == 0:
            deltaNack = stage

        if flags & self.ABANDONMENT or self.stage < (stage - deltaNack):
            logging.debug('Flow.fragmentHandler() abandonment signal flag: %02x'%(flags,))
            toRemove = []
            for index, frag in self.fragments.iteritems():
                if index > stage: # abandon all stages <= stage
                    break
                if index <= (stage - 1):
                    self.fragmentSortedHandler(index, frag.data, frag.flags)
                toRemove.append(index)
            for index in toRemove: del self.fragments[index]
            nextStage = stage
        if stage > nextStage: # not following stage!
            if stage not in self.fragments:
                self.fragments[stage] = Fragment(fragment, flags)
                if len(self.fragments) > 100:
                    logging.debug('Flow.fragmentHandler() fragments %d'%(len(self.fragments),))
            else:
                logging.debug('Flow.fragmentHandler() stage %u on flow %u already received'%(stage, self.id))
        else:
            self.fragmentSortedHandler(nextStage, fragment, flags)
            nextStage += 1
            toRemove = []
            for index, frag in self.fragments.iteritems():
                if index > nextStage:
                    break
                self.fragmentSortedHandler(nextStage, frag.data, frag.flags)
                nextStage += 1
                toRemove.append(index)
            for index in toRemove: del self.fragments[index]

    def fragmentSortedHandler(self, stage, fragment, flags):
        if stage <= self.stage:
            logging.debug('Flow.fragmentSortedHandler() stage %u not sorted on flow %u'%(stage, self.id))
            return
        if stage > (self.stage + 1): # not following stage
            self.lostFragmentsHandler(stage - self.stage - 1)
            self.stage, self.packet = stage, None
            if flags & self.WITH_BEFOREPART:
                return
        else:
            self.stage = stage

        msg = fragment
        if flags & self.WITH_BEFOREPART:
            if self.packet:
                logging.debug('Flow.fragmentSortedHandler() a beforepart message received with previous buffer empty. possible some packets lost')
                self.packet = None
                return
            self.packet.add(fragment)
            if flags & self.WITH_AFTERPART:
                return
            msg = self.packet.data
        elif flags & self.WITH_AFTERPART:
            if self.packet:
                logging.debug('Flow.fragmentSortedHandler() received not beforepart but previous buffer exists')
                self.packet = None
            self.packet = Packet(fragment)
            return
        type, remaining = self.unpack(msg)
        if type != self.EMPTY:
            self.writer.callbackHandle = 0
            name, reader = None, amf.AMF0(remaining)
            if type == self.AMF_WITH_HANDLER or type == self.AMF:
                name = reader.read()
                logging.debug('COMMAND name=%r'%(name,))
                if type == self.AMF_WITH_HANDLER:
                    self.writer.callbackHandle = reader.read()
            # TODO: check for correct indentation
            try:
                if type == self.AMF_WITH_HANDLER or type == self.AMF:
                    self.messageHandler(name, reader)
                elif type == self.AUDIO:
                    self.audioHandler(remaining)
                elif type == self.VIDEO:
                    self.videoHandler(remaining)
                else:
                    self.rawHandler(type, remaining)
            except Exception as err:
                logging.error('flow error: %s' % err)
                self.error = 'flow error ' + str(sys.exc_info()[2])
        self.writer.callbackHandler, self.packet = 0, None
        if flags & self.END:
            if not self.completed and self.writer.signature:
                logging.debug('Flow.fragmentSortedHandler() flow consumed: %r'%(self.id,))
            self.completed = True

    def messageHandler(self, name, message):
        logging.debug('Flow.messageHandler() unknown message: %r name=0x%02x data=%r'%(self.id, name, message))

    def rawHandler(self, type, data):
        logging.debug('Flow.rawHandler() raw unknown message: %r type=0x%02x data=%r'%(self.id, type, data))

    def audioHandler(self, packet):
        logging.debug('Flow.audioHandler() audio packet untreated for flow %r'%(self.id,))

    def videoHandler(self, packet):
        logging.debug('Flow.videoHandler() video packet untreated for flow %r'%(self.id,))

    def lostFragmentsHandler(self, count):
        logging.debug('Flow.lostFragmentsHandler() %d fragments lost on flow %r'%(count, self.id))

    def commitHandler(self):
        pass


class FlowConnection(Flow):
    signature = '\x00\x54\x43\x04\x00'

    def __init__(self, id, peer, server, session):
        Flow.__init__(self, id, self.signature, peer, server, session)
        self._streamIndex = set()
        self.writer.critical = True

    def close(self):
        Flow.close(self)
        for stream in self._streamIndex:
            self.server.streams.destroy(stream)

    def messageHandler(self, name, reader):
        if name == 'connect':
            data = reader.read() # dict or amf.Object
            logging.debug('CONNECT data=%r'%(data.__dict__,))
            [setattr(self.peer, x, getattr(data, x) if hasattr(data, x) else '') for x in ('swfUrl', 'pageUrl')]
            if hasattr(data, 'objectEncoding') and data.objectEncoding != 3.0:
                raise ValueError('objectEncoding must be AMF3 and not [%r]'%(data.objectEncoding,))
            self.server.count += 1
            self.peer.state = Peer.REJECTED
            if not self.server.onConnect(self.peer, self.writer):
                raise ValueError('client rejected')
            self.peer.state = Peer.ACCEPTED
            logging.debug('CONNECT SUCCESS')
            self.writer.writeAMFMessage('_result', amf.Object(level='status', code='NetConnection.Connect.Success', description='Connection succeeded', objectEncoding=3, data=self.peer.data))
        elif name == 'setPeerInfo':
            try:
                self.peer.privateAddress[:] = []
                reader.read()
                while True:
                    address = reader.read()
                    self.peer.privateAddress.append(_ipport2address(address))
            except EOFError: pass
            self.writer.writeRawMessage(struct.pack('>HII', 0x29, self.server.keep_alive_server, self.server.keep_alive_peer))
        elif name == 'initStream':
            pass
        elif name == 'createStream':
            streamId = self.server.streams.create()
            self._streamIndex.add(streamId)
            self.writer.writeAMFMessage('_result', streamId)
        elif name == 'deleteStream':
            index = reader.read()
            self._streamIndex.remove(index)
            self.server.streams.destroy(index)
        else:
            if not self.server.onMessage(self.peer, name, reader, self.writer):
                self.writer.writeAMFMessage('_error', amf.Object(level='error', code='NetConnection.Call.Failed', description="Method '%s' not found"%(name,)))

class FlowGroup(Flow):
    signature = '\x00\x47\x43'

    def __init__(self, id, peer, server, session):
        Flow.__init__(self, id, self.signature, peer, server, session)
        self._bestPeers, self._group = [], None
        self.writer.flowId = id

    def close(self):
        Flow.close(self)
        if self._group:
            self._group.remove(self.peer)

    def rawHandler(self, type, data):
        if type == 0x01:
            if len(data) > 0:
                groupId, data = _unpackString(data)
                self._group = self.server.group(groupId)
                self._bestPeers = self._group.peers.best(self.peer)
                self._group.add(self.peer)
                while self._bestPeers:
                    best = self._bestPeers.pop(0)
                    self.writer.writeRawMessage('\x0b' + best.id, True)
        else:
            Flow.rawHandler(self, type, data)


class FlowNull(Flow):
    def __init__(self, peer, server, session):
        Flow.__init__(self, id, '', peer, server, session)

    def close(self):
        Flow.close(self)

    def fragmentHandler(self, stage, deltaNack, fragment, flags):
        self.fail('message received for an unknown flow')
        self.stage = stage


class FlowStream(Flow):
    signature = '\x00\x54\x43\x04'
    IDLE, PUBLISHING, PLAYING = 0, 1, 2

    def __init__(self, id, signature, peer, server, session):
        Flow.__init__(self, id, signature, peer, server, session)
        self._state, self._isVideo, self._lostFragments = FlowStream.IDLE, False, 0
        self._index, _ = _unpackLength7(signature[4:])
        self._publication = self.server.streams.publications(self._index)

    def close(self):
        Flow.close(self)
        self.disengage()

    def disengage(self):
        if self._state == FlowStream.PUBLISHING:
            self.server.streams.unpublish(self.peer, self._index, self.name)
            self.writer.writeAMFMessage('onStatus', amf.Object(level='status', code='NetStream.Unpublish.Success', description="'%s' is now unpublished"%(self.name,)))
        elif self._state == FlowStream.PLAYING:
            self.server.streams.unsubscribe(self.peer, self._index, self.name)
            self.writer.writeAMFMessage('onStatus', amf.Object(level='status', code='NetStream.Play.Stop', description="Stopped playing '%s'"%(self.name,)))
        self.state = FlowStream.IDLE

    def audioHandler(self, data):
        if self._publication and self._publication.publisherId == self._index:
            self._publication.pushAudioPacket(self.peer, struct.unpack('>I', data[:4])[0], data[4:], self._lostFragments)
            self._lostFragments = 0
        else:
            self.fail('an audio packet is received with no publisher stream')

    def videoHandler(self, data):
        if self._publication and self._publication.publisherId == self._index:
            self._publication.pushVideoPacket(self.peer, struct.unpack('>I', data[:4])[0], data[4:], self._lostFragments)
            self._lostFragments = 0
        else:
            self.fail('a video packet is received with no publisher stream')

    def commitHandler(self):
        if self._publication and self._publication.publisherId == self._index:
            self._publication.flush()

    def rawHandler(self, type_, data):
        flag = struct.unpack('>H', data[:2])[0]
        if flag == 0x22:
            return
        logging.debug('FlowStream.rawHandler() unknown raw flag %u on %r' % (flag, self.id))
        Flow.rawHandler(self, type_, data)

    def lostFragmentsHandler(self, count):
        if self._publication:
            self._lostFragments += count
        Flow.lostFragmentsHandler(self, count) # TODO: remove in unreliable stream case.

    def messageHandler(self, action, msg):
        if action == '|RtmpSampleAccess':
            msg.read()
            msg.read()
        elif action == 'play':
            self.disengage()
            self._state = FlowStream.PLAYING
            self.name = msg.read()
            try:
                start = msg.read()
            except:
                start = -2
            writer = amf.AMF0()
            writer.write('|RtmpSampleAccess')
            writer.write(False)
            writer.write(False)
            self.writer.writeRawMessage(struct.pack('>BIB', 0x0f, 0x00, 0x00) + writer.data.read(), True)
            self.writer.writeAMFMessage('onStatus', amf.Object(level='status', code='NetStream.Play.Reset', description='Playing and resetting "%s"'%(self.name,)))
            self.writer.writeAMFMessage('onStatus', amf.Object(level='status', code='NetStream.Play.Start', description='Started playing "%s"'%(self.name,)))
            self.server.streams.subscribe(self.peer, self._index, self.name, self.writer, start)
        elif action == 'closeStream':
            self.disengage()
        elif action == 'publish':
            self.disengage()
            self.name = msg.read()
            try: type = msg.read()
            except: type = 'live'
            if self.server.streams.publish(self.peer, self._index, self.name, type):
                self.writer.writeAMFMessage('onStatus', amf.Object(level='status', code='NetStream.Publish.Start', description='"%s" is now published'%(self.name,)))
                self._state = FlowStream.PUBLISHING
            else:
                self.writer.writeAMFMessage('onStatus', amf.Object(level='status', code='NetStream.Publish.BadName', description='"%s" is already publishing'%(self.name,)))
        else:
            Flow.messageHandler(self, action, msg)


class FlowWriter(object):
    def __init__(self, signature, session):
        self.id = self.flowId = self.stage = self._lostMessages = self.callbackHandle = self._resetCount = 0
        self._trigger, self._messageNull = Trigger(), None
        self.critical = self.closed = False
        self._messages = []
        self.signature, self.session = signature, session
        session.initFlowWriter(self)

    def dup(self):
        result = FlowWriter(self.signature, self.session)
        result.id, result.stage, result.critical = self.id, self.stage, self.critical
        self.close()

    def clearMessages(self, exceptLast=False): # TODO: this is also the destructor
        while len(self._messages) > (exceptLast and 1 or 0):
            self._messages.pop(0) # TODO: no destructor found
            self._lostMessages += 1
        if not self._messages:
            self._trigger.stop()

    def close(self):
        if self.closed:
            return
        self.clearMessages(True)
        if self.stage > 0 and self.count == 0:
            self.createMessage(buffered=True) # send END | ABANDONMENT in case the receiver was created
        self.closed = True # sets the END flag
        self.flush()

    def fail(self, error):
        logging.debug('FlowWriter.fail() %u failed: %s'%(self.id, error))
        self.clearMessages()
        self.session.resetFlowWriter(self.dup())
        self.session.initFlowWriter(self)
        self.stage = 0
        self._resetCount += 1
        self.reset(self._resetCount)

    def reset(self, count):
        # TODO:
        pass

    @property
    def count(self):
        return len(self._messages)

    @property
    def consumed(self):
        return self.closed and not self._messages

    def ackMessageHandler(self, content, size, lostMessages):
        pass

    def acknowledgment(self, stage):
        if stage > self.stage:
            logging.debug('FlowWriter.fail() ack received higher than current sending stage: %d instead of %d'%(stage, self.stage))
            return
        hasNack = not self._messages and self._messages[0].fragments
        startStage = self._messages[0].startStage if hasNack else (stage + 1)
        count = stage - startStage
        if count == 0: # ack is repeated and is just below the last nack
            return
        if count < 0:
            logging.debug('FlowWriter.fail() ack of stage %d received lower than all nack of flow %d'%(stage, self.id))
            return
        index = 0
        while count > 0 and self._messages and self._messages[index].fragments:
            msg = self._messages[0]
            while count > 0 and msg.fragments:
                msg.fragments.pop(0)
                count -= 1
                msg.startStage += 1
            if not msg.fragments:
                size = 0
                self.ackMessageHandler(msg.memAck(size), size, self._lostMessages)
                self._lostMessages = 0
                self._messages.pop(0)
        if self._messages and self._messages[0].fragments:
            self._trigger.reset()
        else:
            self._trigger.stop()

    def manage(self, server):
        try:
            if not self._trigger.dispatch():
                return
        except:
            self.clearMessages()
            raise
        self.raiseMessage()

    def raiseMessage(self):
        if not self._messages or not self._messages[0].fragments:
            self._trigger.stop()
            return
        logging.debug('   FlowWriter.raiseMessage() calling flush')
        self.session.flush(Session.WITHOUT_ECHO_TIME) # to repeat before we send waiting messages
        header, deltaNack, index = True, 0, 0
        while self._messages and index < len(self._messages):
            msg = self._messages[index]
            if not msg.repeatable:
                if index == 0:
                    self._messages.pop(0)
                    self._lostMessages += 1
                    if not self._messages:
                        self._trigger.stop()
                else:
                    deltaNack += len(msg.fragments)
                    index += 1
                continue

            stage = msg.startStage
            end = False
            available = msg.fragments[0] if msg.fragments else 0
            fragment = msg.fragments[0] if msg.fragments else None
            index = 0

            while not end and index < len(msg.fragments):
                index += 1
                size, end = available, (index == (len(msg.fragments) - 1))
                if not end:
                    size, fragment = msg.fragments[index] - fragment, msg.fragments[index]
                flags = (stage == 0 and Flow.HEADER or 0) | (self.closed and Flow.END or 0) | (stage > msg.startStage and Flow.WITH_BEFOREPART or 0) | (not end and Flow.WITH_AFTERPART or 0)

                data = chr(flags)
                if header:
                    data += _packLength7(self.id) + _packLength7(stage+1) + _packLength7(deltaNack+1)
                    if stage - deltaNack == 0:
                        data += _packString(self.signature, sizeLength=8)
                        if self.flowId > 0:
                            data += struct.pack('>BB', (1+_sizeLength7(self.flowId)), 0x0a) + _packLength7(self.flowId)
                        data += chr(0x00)
                data += msg.data(size)
                self.session.writeMessage(header and 0x10 or 0x11, data)
                header = False

    def flush(self, full=False):
        logging.debug('   FlowWriter.flush(full=%r)'%(full,))
        header = not self.session.canWriteFollowing(self)
        deltaNack = 0
        for msg in self._messages:
            if msg.fragments:
                deltaNack += len(msg.fragments)
                continue
            self._trigger.start()
            msg.startStage = self.stage
            fragments = 0
            available, reader = msg.reader()
            while True:
                logging.debug('   FlowWriter.flush() writer=%r'%(self.session._writer))
                self.session._writer.limit = 1181
                if self.session._writer.available() < 1:
                    self.session.flush(Session.WITHOUT_ECHO_TIME)
                    header = True
                head = header
                size = available + 4
                if head:
                    hbytes = _packLength7(self.id) + _packLength7(self.stage+1) + _packLength7(deltaNack+1)
                    logging.debug('   FlowWriter.flush() stage=%r deltaNack=%r'%(self.stage, deltaNack))
                    if self.stage - deltaNack == 0:
                        hbytes += _packString(self.signature, sizeLength=8)
                        if self.flowId > 0:
                            hbytes += struct.pack('>BB', (1+_sizeLength7(self.flowId)), 0x0a) + _packLength7(self.flowId)
                        hbytes += chr(0x00)
                    size += len(hbytes)
                    logging.debug('   FlowWriter.flush() hbytes=%r'%(hbytes,))
                flags = (self.stage == 0 and Flow.HEADER or 0) | (self.closed and (Flow.END | Flow.ABANDONMENT) or 0) | (fragments > 0 and Flow.WITH_BEFOREPART or 0)
                if size > self.session._writer.available():
                    flags |= Flow.WITH_AFTERPART
                    size = self.session._writer.available()
                    header = True
                else:
                    header = False
                size -= 4
                self.stage += 1

                data = chr(flags)
                if head:
                    data += hbytes
                    size -= len(hbytes)

                available -= size
                data += reader.read(size)
                self.session.writeMessage(head and 0x10 or 0x11, data)
                msg.fragments.append(fragments)
                fragments += size

                if available <= 0:
                    break
        if full:
            self.session.flush()

    def createMessage(self, buffered, data=None, memAck=None):
        if self.closed or not self.signature:
            return None
        message = Message(repeatable=buffered, data=data, memAck=memAck)
        self._messages.append(message)
        logging.debug('   FlowWriter.createMessage(). new count=%d'%(len(self._messages,)))
        if len(self._messages) > 100:
            logging.debug('FlowWriter.createMessage() flow messages size=%d'%(len(self._messages)))
        return message

    def writeRawMessage(self, data, withoutHeader=False):
        logging.debug('   writeRawMessage()')
        msg = self.createMessage(buffered=True)
        if not withoutHeader:
            msg.stream.write(struct.pack('>BI', 0x04, 0))
        msg.stream.write(data)
        return msg

    def writeAMFMessage(self, name, *args):
        logging.debug('   writeAMFMessage(name=%r, args=%r)'%(name, args))
        msg = self.createMessage(buffered=True)
        msg.stream.write(struct.pack('>BI', 0x14, 0))
        for arg in (name, self.callbackHandle, None) + args:
            msg.amfWriter.write(arg)
        return msg

class StreamWriter(FlowWriter):
    def __init__(self, type, signature, session):
        FlowWriter.__init__(self, signature, session)
        self.type, self.reseted, self.qos = type, False, QoS()

    def write(self, tm, data, unbuffered):
        if unbuffered:
            if len(data) >= 5:
                self.createMessage(buffered=False, data=data[:5] + struct.pack('>BI', self.type, tm) + data[5:]) # XXX: no used
                self.flush()
                return
            self.writeRawMessage(struct.pack('>BI', self.type, tm) + data, True)

    def ackMessageHandler(self, content, lostMessages):
        type = ord(content[0])
        if type != self.type:
            return
        tm = struct.unpack('>I', content[1:5])[0]
        self.qos.add(tm, 1, lostMessages)

    def reset(self, count):
        self.reseted = True
        self.qos.reset()


class AudioWriter(StreamWriter):
    def __init__(self, signature, session):
        StreamWriter.__init__(self, 0x08, signature, session)


class VideoWriter(StreamWriter):
    def __init__(self, signature, session):
        StreamWriter.__init__(self, 0x09, signature, session)


class Listener(object):
    def __init__(self, id, publication, writer, unbuffered):
        self.id, self.publication, self.writer, self.unbuffered = id, publication, writer, unbuffered
        self._boundId = self._deltaTime = self._addingTime = self._time = 0
        self._firstKeyFrame = False
        self._audioWriter, self._videoWriter = writer.newFlowWriter(AudioWriter), writer.newFlowWriter(VideoWriter)
        self.writeBounds()

    def close(self):
        self._audioWriter.close()
        self._videoWriter.close()

    @property
    def audioQoS(self):
        return self._audioWriter.qos

    @property
    def videoQoS(self):
        return self._videoWriter.qos

    def computeTime(self, tm):
        if tm == 0:
            tm = 1
        if self._deltaTime == 0 and self._addingTime == 0:
            self._deltaTime = tm
            logging.debug('Listener.computeTime() deltatime %u'%(self._deltaTime,))
        if self._deltaTime > tm:
            logging.debug('Listener.computeTime() time lower than deltaTime on listener %d'%(self.id,), tm, self._deltaTime)
            self._deltaTime = tm
        self._time = tm - self._deltaTime + self._addingTime
        return self._time

    def writeBound(self, writer):
        logging.debug('Listener.writeBound() writing bound %d on flow writer %d'%(self._boundId, writer.id))
        writer.writeRawMessage(struct.pack('>HII', 0x22, self._boundId, 3)) # 3 tracks

    def writeBounds(self):
        self.writeBound(self._videoWriter)
        self.writeBound(self._audioWriter)
        self.writeBound(self.writer)
        self._boundId += 1

    def startPublishing(self, name):
        self.writer.writeAMFMessage('onStatus', amf.Object(level='status', code='NetStream.Play.PublishNotify', description='"%s" is now published'%(name,)))
        self._firstKeyFrame = False

    def stopPublishing(self, name):
        self.writer.writeAMFMessage('onStatus', amf.Object(level='status', code='NetStream.Play.UnpublishNotify', description='"%s" is now unpublished'%(name,)))
        self._deltaTime, self._addingTime = 0, self._time
        self._audioWriter.qos.reset()
        self._videoWriter.qos.reset()

    def pushVideoPacket(self, tm, data):
        if ord(data[0]) & 0xf0 == 0x10: # key frame
            self._firstKeyFrame = True
        if not self._firstKeyFrame:
            logging.debug('Listener.pushVideoPacket() video frame dropped for listener %u to wait first key frame'%(self.id,))
            self._videoWriter.qos.droppedFrames += 1
            return
        if self._videoWriter.reseted:
            self._videoWriter.reseted = False
            self.writeBounds()
        self._videoWriter.write(self.computeTime(tm), data, self.unbuffered)

    def pushAudioPacket(self, tm, data):
        if self._audioWriter.reseted:
            self._audioWriter.reseted = False
            self.writeBounds()
        self._audioWriter.write(self.computeTime(tm), data, self.unbuffered)

    def flush(self):
        self._audioWriter.flush()
        self._videoWriter.flush()
        self.writer.flush()


#--------------------------------------
# CONTROL: Session, Handshake
#--------------------------------------

class PacketWriter(object):
    MAX_SIZE = 1181
    def __init__(self):
        self.data, self.pos, self.limit = '', 0, self.MAX_SIZE
    def available(self):
        return self.limit - self.pos
    def clear(self):
        self.data, self.pos, self.limit = '', 0, self.MAX_SIZE
    def write(self, data):
        logging.debug('   PacketWriter.write(len=%r)'%(len(data),))
        if len(self.data) + len(data) > self.limit:
            raise ValueError('exceeds limit %d+%d>%d'%(len(self.data), len(data), self.limit))
        self.data += data
        self.pos += len(data)
    def __repr__(self):
        return '<Writer pos=%r limit=%r data=%r/>'%(self.pos, self.limit, self.data)

class Trigger(object):
    def __init__(self):
        self._timeInit, self._cycle, self._time, self._running = time.time(), -1, 0, False
    def reset(self):
        self._timeInit, self._cycle, self._time = time.time(), -1, 0
    def start(self):
        if not self._running:
            self.reset()
            self._running = True
    def stop(self):
        self._running = False
    def dispatch(self):
        if not self._running:
            return False
        if self._time == 0 and self._timeInit < time.time() - 1.0:
            return False
        self._time += 1
        if self._time >= self._cycle:
            self._time = 0
            self._cycle += 1
            if self._cycle >= 7:
                raise ValueError('repeat trigger failed')
            logging.debug('Trigger.dispatch() repeat trigger cycle 0x%02x'%(self._cycle + 1,))
            return True
        return False

class Session(object):
    SYMMETRIC_ENCODING, WITHOUT_ECHO_TIME = 0x01, 0x02
    def __init__(self, server, id, farId, peer, dKey, eKey):
        self.server, self.id, self.farId, self.peer = server, id, farId, peer
        self.died = self.failed = self.checked = False
        self._aesDecrypt, self._aesEncrypt = AESDecrypt(dKey), AESEncrypt(eKey)
        self._timesFailed = self._recvTs = self._timeSent = self._nextFlowWriterId = self._timesKeepalive = 0
        self._target = self._lastFlowWriter = None
        self._flows, self._flowWriters, self._handshakeAttempts = {}, {}, {}
        self._writer = PacketWriter()
        self._recvTs = time.time() # TODO: is this correct?

    def __repr__(self):
        return '<Session id=%r farId=%r peer=%r />'%(self.id, self.farId, self.peer)

    def close(self):
        self.kill()
        if self.peer.state != 'none':
            logging.debug('onDisconnect client handler has not been called on the session "%s"' % self.id)
        for flow in self._flows.itervalues():
            flow.close()

    def kill(self):
        if self.died:
            return
        if self.peer.state != Peer.NONE:
            self.peer.state = Peer.NONE
            self.server.onDisconnect(self.peer)
            self.server.count -= 1
        self.died = self.failed = True

    def manage(self):
        if self.died:
            return
        if self.failed:
            return self.failSignal()
        if self._recvTs <= time.time() - 360: # 6 min has elapsed.
            logging.debug('Session.manage() timeout recvTs=%r time=%r'%(self._recvTs, time.time()))
            return self.fail('timeout no client message')
        if self._recvTs <= time.time() - 120 and not self.keepAlive(): # start keepalive server after 2 min.
            return
        toDelete = []
        for id, flowWriter in self._flowWriters.iteritems():
            if flowWriter.consumed:
                flowWriter.clearMessages()
                toDelete.append(id)
            else:
                try:
                    flowWriter.manage(self.server)
                except Exception as err:
                    if flowWriter.critical:
                        logging.error('flow manage error: %s' % err)
                        return self.fail(sys.exc_info()[1]) # should we kill the entire session if flow fails and is critical?
                continue
        for id in toDelete:
            del self._flowWriters[id]
        self.flush()

    def keepAlive(self):
        logging.debug('Session.keepAlive() server')
        if self._timesKeepalive == 10:
            self.fail('timeout keepalive attempts')
            return False
        self._timesKeepalive += 1
        self.writeMessage(0x01, '')
        return True

    def fail(self, error):
        if self.failed:
            return
        self.failed = True
        if self.peer.state != Peer.NONE:
            self.server.onFailed(self.peer, error)
        for flowWriter in self._flowWriters.itervalues():
            flowWriter.close()
        self._writer.clear()
        self.peer.close()
        logging.debug('Session.fail() warning: session failed on the server side: %s'%(error,))
        self.failSignal()

    def failSignal(self):
        if self.died:
            logging.debug('Session.failSignal() warning: fail is useless because session is already dead')
        if not self.failed:
            logging.debug('Session.failSignal() warning: here flag failed should be put with setFailed method. fail() method just allows the fail packet sending')
            self.failed = True
        self._timesFailed += 1
        self._writer.limit = 1181
        self._writer.write(struct.pack('>BH', 0x0c, 0))
        self.flush(Session.WITHOUT_ECHO_TIME)
        if self._timesFailed == 10 or self._recvTs < time.time() - 360: # after 6 min or 10 fails
            self.kill()

    def handshakeP2P(self, address, tag, session):
        logging.debug('Session.handshakeP2P() peer newcomer address send to peer %u connected'%(self.id,))
        paddress = None
        if session:
            if tag not in self._handshakeAttempts:
                self._handshakeAttempts[tag] = 0
                if address == self.peer.address and session.peer.privateAddress:
                    self._handshakeAttempts[tag] = 1
            if self._handshakeAttempts[tag] > 0:
                paddress = session.peer.privateAddress[self._handshakeAttempts[tag] - 1]
            self._handshakeAttempts[tag] += 1
            if self._handshakeAttempts[tag] > len(session.peer.privateAddress):
                self._handshakeAttempts[tag] = 0

        assert len(self.peer.id) == 32
        logging.debug('Session.handshakeP2P() paddress=%r address=%r'%(paddress, address))
        data = struct.pack('>BBB', 0x22, 0x21, 0x0F) + self.peer.id + (_packAddress(paddress, False) if paddress else _packAddress(address, True)) + tag
        self.writeMessage(0x0F, data)
        self.flush()

    def flush(self, flags=0, message=''):
        self._lastFlowWriter = None
        data = message or self._writer.data
        if len(data) > 0:
            now = time.time()
            timeEcho = not (flags & self.WITHOUT_ECHO_TIME) and (self._recvTs >= (now - 30))
            symmetric = flags & self.SYMMETRIC_ENCODING
            marker = symmetric and 0x0b or 0x4a
            logging.debug('   Session.flush() timeEcho=%r symmetric=%r marker=0x%02x'%(timeEcho, symmetric, marker))
            if timeEcho:
                marker += 4
            data = '\x00' * 6 + \
                    struct.pack('>BH', marker, int(now*1000/4) & 0xffff) + \
                    (struct.pack('>H', self._timeSent + (int((now - self._recvTs)*1000/4) & 0xffff)) if timeEcho else '') + \
                    data
            logging.debug('   Session.flush() encoding [%d]\n   %s'%(len(data[6:]), truncate(data[6:], size=100)))
            data = _encode(self._aesEncrypt, data)
            logging.debug('   session.id=%r'%(self.farId,))
            data = _packId(data, self.farId)
            for _ in (0, 1, 2):
                if len(data) == self.server.send(data, self.peer.address):
                     break
            else:
                logging.debug('Session.flush() socket send error on sessin %u, all data was not sent' % self.id)
            if not message:
                self._writer.clear()

    def writeMessage(self, type_, data, flowWriter=None):
        self._writer.limit = 1181
        if not self.failed:
            logging.debug('   Session.writeMessage(type=0x%02x, data-len=%r)' % (type_, len(data)))
            self._lastFlowWriter = flowWriter
            if 3 + len(data) > self._writer.available():
                logging.debug('Session.writeMessage() flush as it is full %r' % self._writer.available())
                self.flush(Session.WITHOUT_ECHO_TIME)
            self._writer.limit = self._writer.pos + 3 + len(data)
            self._writer.write(struct.pack('>BH', type_, len(data)) + data)

    def handle(self, data, sender):
        self.peer.address = sender
        if self._target:
            self._target.address = sender
        data = _decode(self._aesDecrypt, data)
        logging.debug('   decoded [%r]\n   %r' % (len(data), data[6:]))
        self._recvTs, index, data = time.time(), 3, data[6:]
        marker, self._timeSent = struct.unpack('>BH', data[:index])
        marker |= 0xF0
        if marker == 0xFD:
            self.peer.ping, index = (int(self._recvTs*1000/4) & 0xffff) - struct.unpack('>H', data[3:5])[0], index + 2
        elif marker != 0xF9:
            logging.debug('   Session.handle() warning: packet marker unknown 0x%02x' % marker)
        logging.debug('   Session.handle() marker=0x%02x timeSent=%r index=%r' % (marker, self._timeSent, index))
        flags = stage = deltaNack = 0
        flow = None
        remaining = data[index:] # remaining data
        # 0x7f:  Packet Fragment (Section 2.3.1)
        # 0x30:  Initiator Hello (Section 2.3.2)
        # 0x0f:  Forwarded Initiator Hello (Section 2.3.3)
        # 0x70:  Responder Hello (Section 2.3.4)
        # 0x71:  Responder Redirect (Section 2.3.5)
        # 0x79:  RHello Cookie Change (Section 2.3.6)
        # 0x38:  Initiator Initial Keying (Section 2.3.7)
        # 0x78:  Responder Initial Keying (Section 2.3.8)
        # 0x01:  Ping (Section 2.3.9)
        # 0x41:  Ping Reply (Section 2.3.10)
        # 0x10:  User Data (Section 2.3.11)
        # 0x11:  Next User Data (Section 2.3.12)
        # 0x50:  Data Acknowledgement Bitmap (Section 2.3.13)
        # 0x51:  Data Acknowledgement Ranges (Section 2.3.14)
        # 0x18:  Buffer Probe (Section 2.3.15)
        # 0x5e:  Flow Exception Report (Section 2.3.16)
        # 0x0c:  Session Close Request (Section 2.3.17)
        # 0x4c:  Session Close Acknowledgement (Section 2.3.18)
        # 0x00:  Ignore/Padding
        # 0xff:  Ignore/Padding
        while remaining and ord(remaining[0]) != 0xFF:
            type_, size = struct.unpack('>BH', remaining[:3])
            logging.debug('   type=0x%02x size=%r' % (type_, size))
            message, remaining = remaining[3:3+size], remaining[3+size:]
            if type_ == 0x0c:
                self.fail('session failed on the client side')
            elif type_ == 0x4c: # session died
                self.kill()
            elif type_ == 0x01:
                self.writeMessage(0x41, '')
                self._timesKeepalive = 0
            elif type_ == 0x41:
                self._timesKeepalive = 0
            elif type_ == 0x5e:
                id_, message = _unpackLength7(message)
            elif type_ == 0x18:
                # This response is sent when we answer with a Acknowledgment negative
                # It contains the id flow
                # I don't unsertand the usefulness...
                # pFlow = &flow(message.read8());
                # stage = pFlow->stageSnd();
                # For the moment, we considerate it like a exception
                self.fail('ack negative from server')
            elif type_ == 0x51: # ack
                id_, message = _unpackLength7(message)
            elif type_ == 0x10: # normal request
                flags, message = ord(message[0]), message[1:]
                id_, message = _unpackLength7(message)
                stage, message = _unpackLength7(message)
                deltaNack, message = _unpackLength7(message)
                stage, deltaNack = stage - 1, deltaNack - 1
                flow = self._flows.get(id_, None)
                if flags & Flow.HEADER:
                    signature, message = _unpackString(message, 8)
                    if not flow:
                        flow = self.createFlow(id_, signature)
                    next_, message = ord(message[0]), message[1:]
                    if next_ > 0:
                        fullduplex, message = ord(message[0]), message[1:]
                        if fullduplex != 0x0A:
                            logging.debug('Session.handle() warning: unknown full duplex header 0x%02x for flow %u' % (fullduplex, id_))
                        else:
                            _, message = _unpackLength7(message)
                        length, message = ord(message[0]), message[1:]
                        while length > 0 and message:
                            logging.debug('Session.handle() warning: unknown message part on flow %u' % id_)
                            message = message[length:]
                            length, message = ord(message[0]), message[1:]
                        if length > 0:
                            logging.debug('Session.handle() error: bad header message part, finished before scheduled')
                if not flow:
                    logging.debug('Session.handle() warning: flow %u not found' % id_)
            elif type_ != 0x11:
                logging.debug('Session.handle() error: unknown message type 0x%02x' % type_)

            if type_ == 0x10 or type_ == 0x11: # special request, in repeat case, following stage request
                stage, deltaNack = stage + 1, deltaNack + 1
                if type_ == 0x11:
                    flags, message = ord(message[0]), message[1:]
                flow.fragmentHandler(stage, deltaNack, message, flags)
                if flow.error:
                    self.fail(flow.error)

            nextType = ord(remaining[0]) if remaining else 0xFF
            if flow and stage > 0 and nextType != 0x11:
                flow.commit()
                if flow.completed:
                    del self._flows[flow.id]
                    flow.close()
                flow = None
        self.flush()

    def flowWriter(self, id_):
        return self._flowWriters.get(id_, None)

    def flow(self, id_):
        result = self._flows.get(id_, None)
        if not result:
            logging.debug('Session.flow() flow %r not found' % id_)
        return result

    def createFlow(self, id_, signature):
        logging.debug('Session.createFlow() id=%r signature=%r' % (id_, signature))
        if id_ in self._flows:
            logging.debug('Session.createFlow() warning: flow %u already created' % id_)
            return self._flows[id_]
        flow = None
        if signature == FlowConnection.signature:
            flow = FlowConnection(id_, self.peer, self.server, self)
        elif signature == FlowGroup.signature:
            flow = FlowGroup(id_, self.peer, self.server, self)
        elif signature[:len(FlowStream.signature)] == FlowStream.signature:
            flow = FlowStream(id_, signature, self.peer, self.server, self)
        else:
            logging.debug('Session.createFlow() error: new unknown flow %r on session %u' % (signature, self.id))
        if flow:
            logging.debug('Session.createFlow() new flow %u on session %u' % (id_, self.id))
            self._flows[id_] = flow
        return flow

    def initFlowWriter(self, flowWriter):
        self._nextFlowWriterId += 1
        while self._nextFlowWriterId == 0 or self._nextFlowWriterId in self._flowWriters:
            self._nextFlowWriterId += 1
        flowWriter.id = self._nextFlowWriterId
        if len(self._flows) > 0:
            flowWriter.flowId = self._flows.values()[0].id
        self._flowWriters[self._nextFlowWriterId] = flowWriter

    def resetFlowWriter(self, flowWriter):
        self._flowWriters[flowWriter.id] = flowWriter

    def canWriteFollowing(self, flowWriter):
        return self._lastFlowWriter == flowWriter


class Handshake(Session):
    '''P2P handshake'''
    def __init__(self, server):
        Session.__init__(self, server, 0, 0, Peer(), _key, _key)
        self._certificate = '\x01\x0A\x41\x0E' + _random(64) + '\x02\x15\x02\x02\x15\x05\x02\x15\x0E' # 4+64+9=77 bytes
        self._cookies = {} # unfinished sessions TODO: need to use auto-generated cookie instead of storing it to avoid SYN flooding DoS.
        logging.debug('Handshake() server id=%r'%(hashlib.sha256(self._certificate).digest(),))

    def close(self):
        for item in self._cookies.values():
            item.close()
        self._cookies.clear()

    def manage(self):
        toRemove = [cookieId for cookieId, cookie in self._cookies.iteritems() if cookie.obsolete]
        for cookieId in toRemove:
            del self._cookies[cookieId]

    def commitCookie(self, session):
        session.checked = True
        toRemove = [cookieId for cookieId, cookie in self._cookies.iteritems() if cookie.id == session.id]
        for cookieId in toRemove:
            del self._cookies[cookieId]
        if not toRemove:
            logging.debug('Handshake.commitCookie() cookie for session[%r] not found' % session.id)

    def handle(self, data, sender):
        self.peer.address = sender
        if self._target:
            self._target.address = sender
        data = _decode(self._aesDecrypt, data)
        logging.debug('   Handshake.handle() decoded length %r' % len(data))
        marker = ord(data[6])
        if marker != 0x0b:
            logging.debug('   Handshake.handle() invalid marker 0x%02x != 0x0b'%(marker,))
            return
        tm, _id, size = struct.unpack('>HBH', data[7:12])
        payload = data[12:12+size]
        logging.debug('   Handshake.handle() tm=%r id=0x%x size=%r' % (tm, _id, size))
        respId, response = self._handshake(_id, payload)
        if respId == 0:
            return
        response = struct.pack('>BH', respId, len(response)) + response
        self._writer.write(response)
        self.flush(self.SYMMETRIC_ENCODING | self.WITHOUT_ECHO_TIME)
        self.farId = 0

    def _handshake(self, id_, payload):
        # 0x30 => initiator hello
        # 0x38 => initiator initial keying
        # 0x70 => responder hello
        # 0x78 => responder initial keying
        # |-------------------------------------------------|
        # | initiator                             responder |
        # |    | initiator hello -------------------> |     |
        # |    | <------------------- responder hello |     |
        # |    | initiator initial keying ----------> |     |
        # |    | <---------- responder initial keying |     |
        # |-------------------------------------------------|
        logging.debug('   handshake id=0x%02x' % id_)
        if id_ == 0x30: # initiator hello
            _, epdLen, type_ = struct.unpack('>BBB', payload[:3])
            epd = payload[3:3+epdLen-1]
            tag = payload[3+epdLen-1:3+epdLen-1+16]
            response = _packString(tag, 8)
            logging.debug('     type=0x%02x\n     epd=%r\n     tag=%r' % (type_, epd, tag))
            if type_ == 0x0f:
                respId, resp = self.server.handshakeP2P(tag, self.peer.address, epd)
                return (respId, response+resp)
            elif type_ == 0x0a:
                cookie = self._createCookie(Cookie(epd))
                cert = self._certificate
                logging.debug('    handshake response type=0x%02x\n     tag=%s\n     cookie=%s\n     cert=%s'%(0x70, truncate(tag), truncate(cookie), truncate(cert)))
                return (0x70, response + cookie + cert)
            else:
                raise ValueError('unknown handshake type 0x%x' % type_)
        elif id_ == 0x38: # initiator initial keying
            self.farId = struct.unpack('>I', payload[:4])[0]
            cookieId, payload = _unpackString(payload[4:])
            logging.debug('   Handshake.handshake() farId=%r cookieId=[%d] %r...'%(self.farId, len(cookieId), cookieId[:4]))
            if cookieId not in self._cookies:
                raise ValueError('unknown handshake cookie %r'%(cookieId,))
            cookie = self._cookies[cookieId]
            if cookie.id == 0:
                key1, payload = _unpackString(payload)
                self.peer.id = hashlib.sha256(key1).digest()
                logging.debug('   created peer.id=%r'%(self.peer.id,))
                publicKey = key1[-128:]
                key2, payload = _unpackString(payload)
                logging.debug('     far-id=%r\n     cookie-id=%s\n     client-cert=%s\n     client-nonce=%s'%(self.farId, truncate(cookieId), truncate(key1), truncate(key2)))
                dkey, ekey = cookie.computeKeys(publicKey, key2)
                self.peer.path, self.peer.parameters = _url2pathquery(cookie.queryUrl)
                result = self.server.createSession(self.farId, self.peer, dkey, ekey, cookie)
                if result < 0:
                    return (0, '')
                cookie.id = result
                logging.debug('   remaining=%r'%(payload,))
            response = str(cookie)
            logging.debug('   handshake response type=0x%02x\n     id=%r\n     server-nonce=%s' % (0x78, cookie.id, truncate(cookie.nonce)))
            return (0x78, response)
        else:
            raise ValueError('unknown handshake packet id 0x%02x' % id)

    def finishHandshake(self, cookie):
        respId, response = 0x78, str(cookie)
        logging.debug('   handshake continue response type=0x%02x\n     id=%r\n     server-nonce=%s'%(0x78, cookie.id, truncate(cookie.nonce)))
        response = struct.pack('>BH', respId, len(response)) + response
        self._writer.write(response)
        self.flush(self.SYMMETRIC_ENCODING | self.WITHOUT_ECHO_TIME)
        self.farId = 0

    def _createCookie(self, cookie):
        cookieId = _random(64)
        self._cookies[cookieId] = cookie
        return _packString(cookieId, 8)

class Middle(Session):
    def __init__(self, server, id, farId, peer, dKey, eKey, sessions, target):
        Session.__init__(self, server, id, farId, peer, dKey, eKey)
        self.sessions, self.target, self.middlePeer = sessions, target, peer
        self._isPeer, self._middleId, self._firstResponse, self._queryUrl, self._span = target.isPeer, 0, False, 'rtmfp://%s%s' % (_address2ipport(target.address), peer.path), 0
        self._middleAesDecrypt = self._middleAesEncrypt = self._middleDH = self._targetNonce = self._sharedSecret = None

        self._socket = socket.socket(type=socket.SOCK_DGRAM)
        self._socket.bind(('0.0.0.0', 0)) # any random port
        self._gen = self.receiveFromTarget()
        multitask.add(self._gen)

        self.middlePeer.path, self.middlePeer.parameters = _url2pathquery(self._queryUrl)
        self._middleCert = '\x02\x1D\x02\x41\x0E' + _random(64) + '\x03\x1A\x02\x0A\x02\x1E\x02' # 5+64+7=76 bytes
        if self._isPeer:
            self._middleDH, self.middlePeer.id = self.target.DH, self.target.id
            packet = '\x22\x21\x0F' + target.peerId
            logging.debug('   target-handshake type=0x%02x\n     peerId=%s'%(0x30, truncate(target.peerId)))
        else:
            packet = struct.pack('>BBB', len(self._queryUrl)+2, len(self._queryUrl)+1, 0x0A) + self._queryUrl
            logging.debug('   target-handshake type=0x%02x\n     queryUrl=%r'%(0x30, self._queryUrl))
        packet += _random(16)
        logging.debug('     random=%r'%(packet[-16:],))
        logging.debug('   creating Middle()')
        self.sendHandshakeToTarget(0x30, packet)

    def __repr__(self):
        return '<Middle id=%r farId=%r peer=%r />'%(self.id, self.farId, self.peer)

    def close(self):
        Session.close(self)
        if self._gen is not None:
            self._gen.close()
            self._gen = None
        if self._socket:
            self._socket.close()
            self._socket = None

    def receiveFromTarget(self):
        try:
            while True:
                try:
                    data, remote = yield multitask.recvfrom(self._socket, 4096)
                    logging.debug('<= %s:%d [%d] (from target)'%(remote[0], remote[1], len(data)))
                except Exception as err:
                    logging.error('middle socket reception error: %s' % err)
                    return
                if remote != self.target.address:
                    logging.debug('error: received from wrong target %r != %r'%(remote, self.target.address))
                    continue
                if len(data) < 12:
                    logging.debug('error: middle from %r: invalid packet size %r'%(remote, len(data)))
                    continue
                id = _unpackId(data)
                logging.debug('   session.id=%r middleAesDecrypt=%r' % (id, bool(self._middleAesDecrypt)))
                if id == 0 or not self._middleAesDecrypt:
                    data = _decode(self.server._handshake._aesDecrypt, data)
                    logging.debug('   middle handshaking')
                    if ord(data[6]) != 0x0B:
                        logging.debug('target handshake received with non 0x0b marker %02x'%(ord(data[6]),))
                    else:
                        type_, size = struct.unpack('>BH', data[9:12])
                        content = data[12:12+size]
                        self.targetHandshakeHandler(type_, content)
                else:
                    data = _decode(self._middleAesDecrypt, data)
                    logging.debug('   middle packet decoded\n   %s'%(truncate(data[6:], 200),))
                    self.targetPacketHandler(data[6:])
        except GeneratorExit:
            pass
        except Exception as err:
            logging.error('unexpected error in Middle task, error: %s' % err)

    def sendHandshakeToTarget(self, type, data):
        now, marker = time.time(), 0x0b
        data = '\x00'*6 + struct.pack('>BHBH', marker, int(now*1000/4) & 0xffff, type, len(data)) + data
        data = _encode(self.server._handshake._aesEncrypt, data)
        logging.debug('   session.id=%r'%(0,))
        data = _packId(data, 0)
        logging.debug('=> %s:%d [%d] (source=%s:%d)'%(self.target.address[0], self.target.address[1], len(data), self._socket.getsockname()[0], self._socket.getsockname()[1]))
        self._socket.sendto(data, self.target.address)

    def sendToTarget(self, data):
        if not self._middleAesEncrypt:
            logging.debug('critical error: send to target packet impossible because the middle handshake has failed')
            return
        self._firstResponse = True
        data = '\x00'*6 + data
        data = _encode(self._middleAesEncrypt, data)
        logging.debug('   session.id=%r'%(self._middleId,))
        data = _packId(data, self._middleId)
        logging.debug('=> %s:%d [%d] (source=%s:%d)'%(self.target.address[0], self.target.address[1], len(data), self._socket.getsockname()[0], self._socket.getsockname()[1]))
        self._socket.sendto(data, self.target.address)

    def targetHandshakeHandler(self, type, data):
        logging.debug('   target-handshake type=0x%02x'%(type,))
        if type == 0x70:
            tag, data = _unpackString(data, 8)
            cookie, data = _unpackString(data, 8)
            nonce = '\x81\x02\x1D\x02'
            if self._isPeer:
                data = data[4:]
                nonce += self.target.Kp
                logging.debug('     tag=%s\n     cookie=%s\n     public=%s'%(truncate(tag), truncate(cookie), truncate(data[:128])))
                self._sharedSecret = _int2bin(_endDH(self._middleDH[0], _bin2int(data[:128])), 128)
                logging.debug('   shared secret %s'%(truncate(self._sharedSecret),))
            else:
                self._middleDH = _beginDH()
                nonce += self._middleDH[1]
                self.middlePeer.id = hashlib.sha256(nonce).digest()
            logging.debug('   response type=0x%02x\n     id=%r\n     cookie=%s\n     nonce=%s\n     middleCert=%s'%(0x38, self.id, truncate(cookie), truncate(nonce), truncate(self._middleCert)))
            packet = struct.pack('>I', self.id) + _packString(cookie, 8) + _packString(nonce) + _packString(self._middleCert) + '\x58'
            self.sendHandshakeToTarget(0x38, packet)
        elif type == 0x71:
            tag, data = _unpackString(data, 8)
            if self._middleAesDecrypt:
                farId, self.farId = self.farId, 0
                self.flush(Session.SYMMETRIC_ENCODING | Session.WITHOUT_ECHO_TIME)
                self.farId = farId
            else:
                logging.debug('warning: middle mode leaks: redirection request, restart with a url pertinant among the following')
                index = 0
                while index < len(data):
                    if ord(data[index]) == 0x01:
                        a, b, c, d, p = struct.unpack('>BBBBH', data[index+1:index+7])
                        logging.debug('  %u.%u.%u.%u:%u'%(a, b, c, d, p))
                        index += 7
                    else:
                        index += 1
                self.fail('redirection middle request')
                self.kill()
        elif type == 0x78:
            self._middleId, data = struct.unpack('>I', data[:4])[0], data[4:]
            self._targetNonce, data = _unpackString(data)
            logging.debug('     id=%r\n     target-nonce=%s'%(self._middleId, truncate(self._targetNonce)))
            if not self._isPeer:
                key = self._targetNonce[-128:]
                self._sharedSecret = _int2bin(_endDH(self._middleDH[0], _bin2int(key)), len(key))
            dkey, ekey = _asymetricKeys(self._sharedSecret, self._middleCert, self._targetNonce)
            self._middleAesEncrypt, self._middleAesDecrypt = AESEncrypt(dkey), AESDecrypt(ekey)
            logging.debug('   middle shared secret %s'%(truncate(self._sharedSecret),))

            if hasattr(self, '_handshakeCookie'):
                self.server._handshake.finishHandshake(self._handshakeCookie)
        else:
            logging.debug('error: unknown target handshake type 0x%02x'%(type,))

    def handle(self, data, sender):
        self.peer.address = sender
        if self._target:
            self._target.address = sender
        data = _decode(self._aesDecrypt, data)
        logging.debug('   Middle.handle() decoded [%r]\n   %r'%(len(data), data[6:]))
        self._recvTs, index, data = time.time(), 3, data[6:]
        marker, request, index = ord(data[0]), data[:3], 3
        if (marker | 0xf0) == 0xfd:
            logging.debug('   ping=%r'%(struct.unpack('>H', data[3:5])[0],))
            request += data[3:5]
            index += 2

        remaining = data[index:] # remaining data
        while remaining and ord(remaining[0]) != 0xFF:
            _type, size = struct.unpack('>BH', remaining[:3])
            logging.debug('   type=0x%02x' %  _type)
            content, remaining, newdata = remaining[3:3+size], remaining[3+size:], ''
            logging.debug('   content=%s'%(truncate(content),))

            if _type == 0x10:
                first, content = content[0], content[1:]
                idFlow, content = _unpackLength7(content)
                stage, content = _unpackLength7(content)
                newdata = first + _packLength7(idFlow) + _packLength7(stage)
                logging.debug('   first=0x%02x idFlow=0x%02x stage=0x%02x is-peer=%r'%(ord(first), idFlow, stage, self._isPeer))
                if not self._isPeer:
                    if idFlow == 0x02 and stage == 0x01: # replace netconnection info
                        newdata, content = newdata + content[:14], content[14:]
                        tmp, content = _unpackString(content, 16)
                        newdata += _packString(tmp, 16)
                        writer, reader = amf.AMF0(), amf.AMF0(content)
                        writer.write(reader.read()) # should be a number
                        obj = reader.read() # Object
                        if isinstance(obj, amf.Object) and hasattr(obj, 'tcUrl'):
                            obj.tcUrl = self._queryUrl
                        writer.write(obj)
                        newdata += writer.data.getvalue()
                    elif idFlow == 0x02 and stage == 0x02: # replace set peer info
                        newdata, content = newdata + content[:7], content[7:]
                        writer, reader = amf.AMF0(), amf.AMF0(content)
                        name = reader.read()
                        writer.write(name)
                        if name == 'setPeerInfo':
                            writer.write(reader.read()) # number
                            reader.read(); writer.write(None)
                            while not reader.data.eof():
                                address = reader.read()
                                writer.write(address.rpartition(':')[0] + ':' + str(self._socket.getsockname()[1]))
                        newdata += writer.data.getvalue()
                else:
                    if idFlow == 0x02 and stage == 0x01:
                        newdata, content = newdata + content[:5], content[3:]
                        netGroupHeader, content = struct.unpack('>H', content[:2])[0], content[2:]
                        logging.debug('   netGroupHeader=0x%04x'%(netGroupHeader,))
                        if netGroupHeader == 0x4752:
                            newdata, content = newdata + content[:71], content[71:]
                            found = False
                            for group in self.server.groups:
                                if group.hasPeer(self.target.id):
                                    result1 = hmac.new(self._sharedSecret, self._targetNonce, hashlib.sha256).digest()
                                    result2 = hmac.new(group.id, result1[:32]).digest()
                                    newdata, content = newdata + result2[:32], content[32:]
                                    newdata, content = newdata + content[:4], content[4:]
                                    newdata, content = newdata + self.target.peerId, content[32:]
                                    found = True
                                    break
                            if not found:
                                logging.debug('error: handshake netgroup packet between peers without corresponding group')
            elif _type == 0x4C:
                self.kill()

            newdata += content
            logging.debug('   newdata=%s'%(truncate(newdata),))
            request += struct.pack('>BH', _type, len(newdata)) + newdata
            logging.debug('   new request type=0x%02x len=%d' % (_type, len(request)))

        if len(request) > index:
            self.sendToTarget(request)

    def targetPacketHandler(self, data):
        if self._firstResponse:
            self._recvTs = time.time()
        self._firstResponse, index = False, 3
        marker, _ = struct.unpack('>BH', data[:3])
        if marker | 0xF0 == 0xFE:
            self._timeSent, index = struct.unpack('>H', data[3:5])[0], 5
        idFlow = stage = nbPeerSent = 0
        remaining, request = data[index:], '' # remaining data
        while remaining and ord(remaining[0]) != 0xFF:
            type, size = struct.unpack('>BH', remaining[:3])
            logging.debug('   type=0x%02x'%(type,))
            content, remaining = remaining[3:3+size], remaining[3+size:]
            request += struct.pack('>BH', type, size)
            if type == 0x10 or type == 0x11:
                flag, content = ord(content[0]), content[1:]
                request += struct.pack('>B', flag)
                if type == 0x10:
                    idFlow, content = _unpackLength7(content)
                    stage, content = _unpackLength7(content)
                    request += _packLength7(idFlow) + _packLength7(stage)
                    logging.debug('   idFlow=0x%02x stage=0x%02x'%(idFlow, stage))
                else:
                    stage += 1
                if content: # TODO: is this check correct?
                    value, content = _unpackLength7(content)
                    request += _packLength7(value)
                    logging.debug('   flag=0x%02x value=%r'%(flag, value))
                    if not (flag & Flow.WITH_BEFOREPART):
                        if flag & Flow.HEADER:
                            length, request, content = ord(content[0]), request + content[0], content[1:]
                            while length != 0:
                                request, content = request + content[:length], content[length:]
                                length, request, content = ord(content[0]), request + content[0], content[1:]
                        if content: # TODO: sometimes next line gives indexerror, so added if content here.
                            flagType, request, content = ord(content[0]), request + content[0], content[1:]
                            logging.debug('   flagType=0x%02x'%(flagType,))
                            if flagType == 0x09:
                                tm, request, content = struct.unpack('>I', content[:4])[0], request + content[:4], content[4:]
                                logging.debug('   video tm=%r'%(tm,))
                            elif flagType == 0x08:
                                tm, request, content = struct.unpack('>I', content[:4])[0], request + content[:4], content[4:]
                                logging.debug('   audio tm=%r'%(tm,))
                            elif flagType == 0x04:
                                request, content = request + content[:14], content[14:]
                            if flagType == 0x0b and stage == 0x01 and (marker == 0x4e and idFlow == 0x03 or marker == 0x8e and idFlow == 0x05):
                                middlePeerIdWanted, content = content[:32], content[32:]
                                nbPeerSent += 1
                                for middle in self.sessions.itervalues():
                                    if middle.middlePeer == middlePeerIdWanted:
                                        middlePeerIdWanted = middle.peer.id
                                        break
                                logging.debug('   replace middleId by peerId')
                                request += middlePeerIdWanted
                            elif flagType == 0x01:
                                request, content = request + content[:68], content[68:]
                                found = False
                                for group in self.server.groups:
                                    if group.hasPeer(self.target.id):
                                        result1 = hmac.new(self._sharedSecret, self.target.initNonce, hashlib.sha256).digest()
                                        result2 = hmac.new(group.id, result1[:32]).digest()
                                        request, content = request + result2[:32], content[32:]
                                        request, content = request + content[:4], content[4:]
                                        request, content = request + self.target.peerId, content[32:]
                                        found = True
                                        break
                                if not found:
                                    logging.debug('error: handshake NetGroup packet between peers without same group')
            elif type == 0x0F:
                request, content = request + content[:3], content[3:]
                peerId, content = content[:32], content[32:]
                if peerId != self.peer.id and peerId != self.middlePeer.id:
                    logging.debug('warning: the p2p handshake target packet does not match the peerId or middlePeerId')
                request += self.peer.id
            request += content
        if nbPeerSent > 0:
            logging.debug('info %r peers sending'%(nbPeerSent,))
        if request:
            self.flush(flags=0, message=request)

    def failSignal(self):
        Session.failSignal(self)
        if self._middleAesEncrypt:
            data = struct.pack('>BHBH', 0x4a, int(time.time()*1000/4) & 0xffff, 0x4c, 0)
            self.sendToTarget(data)


#--------------------------------------
# CONTROL: FlashServer
#--------------------------------------

class FlashServer(object):
    '''A RTMFP server.'''
    def __init__(self):
        self._handshake = Handshake(self)
        self.sockUdp, self.sessions, self._nextId = None, {0: self._handshake}, 0 # TODO: self._nextId => itertools.count(1) ?
        self.streams, self.count, self.keep_alive_server, self.keep_alive_peer, self._groups, self._timeLastManage = Streams(), 0, 15, 10, [], 0 # from handler

    def close(self):
        [x.close() for x in self._groups] # from handler
        self._groups[:] = []

    def start(self, options):
        self.cirrus, self.middle, self.freq_manage, self.keep_alive_server, self.keep_alive_peer = options.cirrus, options.middle, options.freq_manage, options.keep_alive_server, options.keep_alive_peer
        if not self.sockUdp:
            sock = self.sockUdp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((options.host, options.port))
            logging.debug('FlashServer.start() listening udp on %s:%s' % sock.getsockname())
            multitask.add(self.serverudplistener())

    def stop(self):
        self._handshake.close()
        for session in self.sessions.itervalues():
            session.close()
        self.sessions.clear()
        if self.sockUdp:
            try:
                self.sockUdp.close()
                self.sockUdp = None
            except:
                pass

    def serverudplistener(self, max_size=2048):
        try:
            while True:
                self.manage()
                data, remote = yield multitask.recvfrom(self.sockUdp, max_size)
                logging.debug('<= %s:%d [%d]' % (remote[0], remote[1], len(data)))
                if len(data) < 12:
                    logging.debug('FlashServer.serverudplistener() invalid packet of length %d' % len(data))
                else:
                    sessionId = _unpackId(data)
                    if sessionId not in self.sessions:
                        logging.debug('   session %d not found' % sessionId)
                    else:
                        logging.debug('   session id=%d' % sessionId)
                        session = self.sessions[sessionId]

                        if not isinstance(session, Handshake) and not session.checked:
                            self._handshake.commitCookie(session)
                        try:
                            session.handle(data, remote)
                        except GeneratorExit:
                            raise
                        except StopIteration:
                            raise
                        except Exception as err:
                            logging.error('FlashServer.serverudplistener() session error: %s' % err)
        except GeneratorExit:
            pass # terminate
        except StopIteration:
            raise
        except Exception as err:
            logging.debug('FlashServer.serverudplistener() error: %s' % err)

    def send(self, data, remote): # a wrapper around socket.sendto for local UDP socket
        logging.debug('=> %s:%d [%d]' % (remote[0], remote[1], len(data)))
        return self.sockUdp.sendto(data, remote)

    def group(self, id):
        for group in self._groups:
            if group.operator == id:
                return group
        newGroups = [group for group in self._groups if len(group.peers) > 0]
        if len(self._groups) != len(newGroups):
            self._groups[:] = newGroups
        group = Group(id)
        self._groups.append(group)
        return group

    def createSession(self, farId, peer, dkey, ekey, cookie):
        while self._nextId in self.sessions: self._nextId += 1
        target = None
        if self.middle:
            if not cookie.target:
                cookie.target = Target(peer.address, cookie)
                cookie.target.peerId = peer.id
                peer.id = cookie.target.id
                logging.debug('   changed peer id %r to %r'%(cookie.target.peerId, cookie.target.id))
                logging.info('------------------------\nto connect peer %s use %s\n------------------------' % (_bin2hex(cookie.target.peerId), _bin2hex(cookie.target.id)))
            else:
                target = cookie.target
        if target:
            session = Middle(self, self._nextId, farId, peer.dup(), dkey, ekey, self.sessions, target)
            logging.debug('   created %r' % session)
            logging.debug('   waiting for handshake completion from middle')
            session._handshakeCookie = cookie
            self.sessions[session.id] = session
            cookie.id = session.id
            return -1
        else: # normal scenario without middle
            session = Session(self, self._nextId, farId, peer.dup(), dkey, ekey)
            session._target = cookie.target
            logging.debug('   created %r' % session)
        self.sessions[session.id] = session
        return session.id

    def handshakeP2P(self, tag, address, peerIdWanted):
        # TODO: we need a better way to associate the session based on the far-id parameter?
        found = [session for session in self.sessions.itervalues() if session.peer.address == address and session != self._handshake]
        session = found and found[0] or None
        sessionWanted = ([s for s in self.sessions.itervalues() if s.peer and s.peer.id == peerIdWanted] + [None])[0]
        logging.debug('   p2p-handshake tag=%r address=%r peerIdWanted=%r found session.id=%r session wanted=%r'%(tag, address, peerIdWanted, session and session.id, sessionWanted and sessionWanted.id))
        # TODO: ignoring cirrus case
        if not sessionWanted:
            logging.debug('FlashServer.handshakeP2P() UDP hole punching: session wanted not found. peerIdWanted=%r sessions=%r'%(peerIdWanted, self.sessions))
            return (0, '')
        elif sessionWanted.failed:
            logging.debug('FlashServer.handshakeP2P() UDP hole punching: session wanted is deleting')
            return (0, '')

        if self.middle:
            logging.debug('   p2p-handshake processing middle mode target=%s' % sessionWanted._target)
            if sessionWanted._target:
                cookieId = self._handshake._createCookie(Cookie(sessionWanted._target))
                response = cookieId + '\x81\x02\x1D\x02' + sessionWanted._target.Kp
                logging.debug('   response id=0x%02x\n     cookie-id=%s\n     public=%s'%(0x70, truncate(cookieId), truncate(sessionWanted._target.Kp)))
                logging.debug('   session-wanted=%s %r\nsession=%s %r'%(sessionWanted.__class__, sessionWanted.__dict__, session.__class__, session.__dict__))
                return (0x70, response)
            else:
                logging.debug('error: peer/peer dumped exchange impossible: no corresponding target with the session wanted')

        sessionWanted.handshakeP2P(address, tag, session)
        response = _packAddress(sessionWanted.peer.address, True)

        logging.debug('   p2p-handshake sessionWanted.peer.privateAddress=%r'%(sessionWanted.peer.privateAddress,))
        for addr in sessionWanted.peer.privateAddress:
            if addr == address:
                continue
            response += _packAddress(addr, False)
        return (0x71, response)

    def manage(self):
        if self._timeLastManage > time.time() - 2:
            return
        self._timeLastManage = time.time()
        self._handshake.manage()
        toDelete = []
        for sessionId, session in self.sessions.iteritems():
            session.manage()
            if sessionId != 0 and session.died:
                logging.debug('FlashServer.manage() note: session %u died'%(session.id,))
                toDelete.append(sessionId)
        for sessionId in toDelete:
            session.close()
            del self.sessions[sessionId]
        if self._timeLastManage < time.time() - 0.020: # more than 20ms
            logging.debug('FlashServer.manage() warning: process management lasted more than 20ms: %d'%(time.time() - self._timeLastManage,))

    # callbacks from the session
    def onConnect(self, client, flowWriter): # return True to accept the session from this client/peer
        # TODO: perform any authentication based on client.parameters. Set any client.data if needed.
        # TODO: perform any status page processing
        return True

    def onDisconnect(self, client): # inform disconnection of session with client/peer
        pass

    def onFailed(self, client, msg):
        logging.debug('FlashServer.onFailed() client failed %s'%(msg,))

    def onMessage(self, client, name, reader, writer):
        logging.debug('FlashServer.onMessage() %s'%(name,))
        # TODO: perform any status message
        return False

    def onPublish(self, client, publication):
        # TODO: add publication
        pass

    def onUnpublish(self, client, publication):
        # TODO: add unpublication
        pass

    def onSubscribe(self, client, listener):
        pass

    def onUnsubscribe(self, client, listener):
        pass

    def onAudioPacket(self, client, publication, time, packet):
        # TODO: update audio QoS
        pass

    def onVideoPacket(self, client, publication, time, packet):
        # TODO: update video QoS
        pass


#--------------------------------------
# MAIN
#--------------------------------------

# The main routine to start, run and stop the service
if __name__ == '__main__':
    from optparse import OptionParser, OptionGroup
    parser = OptionParser()
    parser.add_option('-i', '--host',    dest='host',    default='0.0.0.0', help="listening IP address. Default '0.0.0.0'")
    parser.add_option('-p', '--port',    dest='port',    default=1935, type="int", help='listening port number. Default 1935')
    parser.add_option('-r', '--root',    dest='root',    default='./',       help="document path prefix. Directory must end with /. Default './'")
    parser.add_option('-d', '--verbose', dest='verbose', default=False, action='store_true', help='enable debug trace')
    group = OptionGroup(parser, 'RTMFP related', 'Additional options related to RTMFP rendezvous function')
    group.add_option('',   '--cirrus',  dest='cirrus', default=None, help='Cirrus address of the form "ip:port" to activate a "man-in-the-middle" developer mode in bypassing flash packets to the official cirrus server of your choice, it is a instable mode to help developers, "p2p.rtmfp.net:10000" for example. Default is None')
    group.add_option('',   '--middle',  dest='middle', default=False, action='store_true', help='Enables a "man-in-the-middle" developer mode between two peers. It is a unstable mode to help developers.')
    group.add_option('',   '--freq-manage', dest='freq_manage', type='int', default=2, help='frequency manage in seconds. Default 2')
    group.add_option('',   '--keep-alive-server', dest='keep_alive_server', default=15, type='int', help='Keep alive interval with server. Default 15')
    group.add_option('',   '--keep-alive-peer', dest='keep_alive_peer', default=10, type='int', help='Keep alive interval with peer. Default 10')
    parser.add_option_group(group)
    (options, args) = parser.parse_args()

    logging.basicConfig(level=options.verbose and logging.DEBUG or logging.INFO,
            format='%(asctime)s %(levelname)6s %(message)s',
            stream=sys.stdout)
    if options.cirrus:
        logging.info('main() using cirrus ' + options.cirrus)
        options.freq_manage = 0
    if options.keep_alive_server < 5: options.keep_alive_server = 5
    if options.keep_alive_peer < 5: options.keep_alive_peer = 5

    try:
        agent = FlashServer()
        agent.root = options.root
        agent.start(options)
        logging.debug('Flash Server Starts - %s:%d' % (options.host, options.port))
        multitask.run()
    except KeyboardInterrupt:
        pass
    logging.debug('Flash Server Stops')
