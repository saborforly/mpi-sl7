#!/bin/bash
hydra_nameserver &
time mpiexec -nameserver localhost python /junofs/users/liuyan/OEC/mpi/bin/master.py /junofs/users/liuyan/OEC/mpi/Application/AnalysisApp/App_Module.py /junofs/users/liuyan/OEC/mpi/DistJET/config.ini debug /junofs/users/liuyan/OEC/mpi/Application/AnalysisApp/config.ini
