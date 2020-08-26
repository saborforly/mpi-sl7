# mpi-sl7 完整版，可直接运行  
##  1.系统环境  
  gcc 4.8.5    
  python 2.7    
##  2.环境变量    setup.sh
包含boost-1.55.0 以及mpich-3.2 编译后的lib库，不需要额外安装依赖    
同时python的一些package也已经编译完成    
export PYTHONPATH=/yourpath/mpi-sl7/pylib/lib64/python2.7/site-packages:$PYTHONPATH  
export PATH=$PATH:/yourpath/mpi-sl7/software/mpich/bin
export PATH=$PATH:/yourpath/mpi-sl7/bin
export DistJETPATH=/yourpath/mpi-sl7
export JUNOTOP=/yourpath/mpi-sl7/juno:$JUNOTOP
export LD_LIBRARY_PATH=/yourpath/mpi-sl7/software/boost/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/yourpath/mpi-sl7/software/mpich/lib:$LD_LIBRARY_PATH
