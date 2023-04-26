#!/usr/bin/env python3

import socket
import threading
import os
import time

# pyprox listens to 127.0.0.1:LISTENING_PORT
LISTENING_PORT = 2500

# Can be any Cloudflare ip
CLOUDFLARE_IP = "162.159.135.42"
CLOUDFLARE_PORT = 443
# Length of fragments of client hello-packet (n Bytes in each chunk)
FRAGMENTS_LENGTH = 77
# Sleep between each fragment to make GFW-cache full, so it forgets previous chunks
FRAGMENTS_SLEEP = 0.2

# ignore description below , It's for old code, just leave it intact.
# default for Google is ~21 sec, recommend 60 sec unless you have low ram and need close soon
SOCKET_TIMEOUT = 60
# speed control, avoid server crash if huge number of users flooding (default 0.1)
FIRST_TIME_SLEEP = 0.01
# avoid server crash on flooding request -> max 100 sockets per second
ACCEPT_TIME_SLEEP = 0.01


class ThreadedServer(object):
    def __init__(self, host, port):
        self.host = host
        self.port = port

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))

    def listen(self):

        # up to 128 concurrent unaccepted socket queued,
        # more will be refused until accepting those.
        self.sock.listen(128)
        while True:
            client_sock, client_addr = self.sock.accept()
            client_sock.settimeout(SOCKET_TIMEOUT)

            # avoid server crash on flooding request
            time.sleep(ACCEPT_TIME_SLEEP)
            thread_up = threading.Thread(
                target=lambda: self.upstream(client_sock),
            )

            # avoid memory leak by telling os its belong to main program
            # it's not a separate program, so gc collect it when thread finishes
            thread_up.daemon = True
            thread_up.start()

    def upstream(self, client_sock):

        first_flag = True
        backend_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend_sock.settimeout(SOCKET_TIMEOUT)

        while True:
            try:
                if not first_flag:
                    data = client_sock.recv(4096)
                    if data:
                        backend_sock.sendall(data)
                    else:
                        raise Exception("cli pipe close")
                    continue

                first_flag = False

                # speed control + waiting for packet to fully receive
                time.sleep(FIRST_TIME_SLEEP)

                data = client_sock.recv(16384)
                if not data:
                    raise Exception("cli syn close")

                backend_sock.connect((CLOUDFLARE_IP, CLOUDFLARE_PORT))
                thread_down = threading.Thread(
                    daemon=True,
                    target=lambda: self.downstream(backend_sock, client_sock),
                )
                thread_down.start()
                self.send_data_in_fragment(data, backend_sock)

            except Exception:
                # wait two second for another thread to flush
                time.sleep(2)
                client_sock.close()
                backend_sock.close()
                return False

    @staticmethod
    def downstream(backend_sock, client_sock):
        first_flag = True

        while True:
            try:
                if first_flag:
                    first_flag = False
                    data = backend_sock.recv(16384)
                    if data:
                        client_sock.sendall(data)
                    else:
                        raise Exception("backend pipe close at first")
                    continue

                data = backend_sock.recv(4096)
                if data:
                    client_sock.sendall(data)
                else:
                    raise Exception("backend pipe close")

            except Exception as e:
                # wait two second for another thread to flush
                time.sleep(2)
                backend_sock.close()
                client_sock.close()
                return False

    @staticmethod
    def send_data_in_fragment(data, sock):

        for start in range(0, len(data), FRAGMENTS_LENGTH):
            end = start + FRAGMENTS_LENGTH
            fragment_data = data[start:end]

            print("sending ", len(fragment_data), " Bytes")
            sock.sendall(fragment_data)
            time.sleep(FRAGMENTS_SLEEP)

        print("----------FINISH------------")


if __name__ == "__main__":
    if os.name == "posix":
        try:
            import resource
        except ImportError as e:
            raise ImportError(
                f'"{e.name}" is not installed, '
                'you may install it using "pip install python-resources"'
            ) from e

        # set linux max_num_open_socket from 1024 to 128k
        resource.setrlimit(resource.RLIMIT_NOFILE, (127000, 128000))

    print("Listening on: 127.0.0.1:" + str(LISTENING_PORT))
    ThreadedServer("", LISTENING_PORT).listen()
