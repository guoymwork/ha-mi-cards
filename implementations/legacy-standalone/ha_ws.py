#!/usr/bin/env python3
"""HA WebSocket 客户端（纯标准库）。

用法:
    python3 ha_ws.py '<JSON: {"cmd": "type", ...}>'

HA WS 命令参数必须放在消息顶层（不能嵌套 payload）。
"""
import base64
import json
import os
import socket
import struct
import sys


class HAWS:
    def __init__(self, host="127.0.0.1", port=8123, token=None):
        self.host = host
        self.port = port
        self.token = token or os.environ.get("HA_TOKEN", "")
        self.sock = None
        self._id = 0

    # ---------- WebSocket 帧 ----------
    def _connect(self, path="/api/websocket"):
        s = socket.create_connection((self.host, self.port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Authorization: Bearer {self.token}\r\n"
            "\r\n"
        )
        s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            c = s.recv(4096)
            if not c:
                raise RuntimeError("握手失败")
            buf += c
        self.sock = s

    @staticmethod
    def _mask(data, mk):
        return bytes(b ^ mk[i % 4] for i, b in enumerate(data))

    def _send(self, obj):
        data = json.dumps(obj).encode()
        hdr = bytearray([0x81])
        n = len(data)
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        mk = os.urandom(4)
        hdr += mk
        self.sock.sendall(bytes(hdr) + self._mask(data, mk))

    def _recv(self, timeout=30):
        self.sock.settimeout(timeout)

        def rd(n):
            b = b""
            while len(b) < n:
                c = self.sock.recv(n - len(b))
                if not c:
                    raise RuntimeError("连接关闭")
                b += c
            return b

        b1, b2 = rd(2)
        op = b1 & 0x0F
        masked = b2 & 0x80
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", rd(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", rd(8))[0]
        mk = rd(4) if masked else b""
        pl = rd(ln)
        if masked:
            pl = self._mask(pl, mk)
        if op == 8:
            raise RuntimeError("对端关闭连接")
        return pl.decode("utf-8", "replace")

    # ---------- 业务 ----------
    def handshake(self):
        self._connect()
        msg = json.loads(self._recv())
        if msg.get("type") != "auth_required":
            raise RuntimeError(f"预期 auth_required，实际 {msg}")
        self._send({"type": "auth", "access_token": self.token})
        msg = json.loads(self._recv())
        if msg.get("type") != "auth_ok":
            raise RuntimeError(f"认证失败: {msg}")

    def command(self, ctype, payload=None):
        """发送命令。payload 的键会合并到消息顶层（HA 要求）。"""
        self._id += 1
        msg = {"id": self._id, "type": ctype}
        if isinstance(payload, dict):
            msg.update(payload)
        self._send(msg)
        while True:
            r = json.loads(self._recv())
            if r.get("id") == self._id:
                if not r.get("success"):
                    raise RuntimeError(json.dumps(r.get("error"), ensure_ascii=False))
                return r.get("result")


def main():
    spec = json.loads(sys.argv[1])
    ws = HAWS(host=spec.get("host", "127.0.0.1"), port=spec.get("port", 8123))
    ws.handshake()
    out = ws.command(spec["cmd"], spec.get("args", {}))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
