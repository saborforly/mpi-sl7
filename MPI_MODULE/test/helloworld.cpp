#include <iostream>
#include <string>
#include <boost/python.hpp>   // 必须引入这个头文件

using namespace boost::python;

class HelloWorld{
public:
    HelloWorld(const std::string& name, int age);

    void printInfo();

private:
    std::string m_name;
    int m_age;
};

HelloWorld::HelloWorld(const std::string& name, int age):m_name(name), m_age(age){

}

void HelloWorld::printInfo(){
    std::cout << "我叫" << m_name << ", " << m_age << "岁了" << std::endl;
}

void ceshi(){
    std::cout << "ceshi" << std::endl;
}

BOOST_PYTHON_MODULE(helloworld){
    class_<HelloWorld/* 类名 */, boost::noncopyable /* 单例模式，可有可无 */ > 
            ("helloworld", init<const std::string&, int/* init里面就是放构造函数的参数，不需要实参 */>())//导出类中的方法
            .def("printinfo", &HelloWorld::printInfo);
    def("ceshi",&ceshi);
}
