#!/bin/bash
mpiexec -n 1 -nameserver localhost -f /junofs/users/liuyan/OEC/mpi/DistJET/hostfile python /junofs/users/liuyan/OEC/mpi/bin/worker.py 1 /junofs/users/liuyan/OEC/mpi/DistJET/config.ini debug
#-f /junofs/users/zhaobq/DistJET_Test/hosts.txt
