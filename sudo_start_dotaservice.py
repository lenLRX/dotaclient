import os
import sys


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("usage {} num".format(__file__))
        sys.exit()
    os.system("docker stop $(docker ps -a -q)")
    os.system("docker rm $(docker ps -a -q)")
    dotaservice_port = 13338
    dotaservice_host_port = 13337
    client_num = int(sys.argv[1])

    for i in range(client_num):
        os.system("docker run -it -dp {}:{} dotaservice".format(dotaservice_port + i, dotaservice_host_port))
