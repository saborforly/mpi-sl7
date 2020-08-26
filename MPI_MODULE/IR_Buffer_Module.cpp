//
// Created by zhaobq on 2017-4-25.
//

#include <boost/python.hpp>
#include "Include/IRecv_buffer.h"

using namespace boost::python;

BOOST_PYTHON_MODULE(IR_Buffer_Module){

        class_<IRecv_buffer>("IRecv_buffer")
            .def("get", &IRecv_buffer::get)
            .def("put", &IRecv_buffer::put)
            .def("empty", &IRecv_buffer::empty)
	    .def("size", &IRecv_buffer::size)
        ;
}
