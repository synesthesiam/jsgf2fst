import setuptools

setuptools.setup(
    name="jsgf2fst",
    version="0.0.1",
    author="Michael Hansen",
    author_email="hansen.mike@gmail.com",
    url="https://github.com/synesthesiam/jsgf2fst",
    packages=setuptools.find_packages(),
    install_requires=["openfst==1.6.1", "pyjsgf==1.6.0"],
    classifiers=["Programming Language :: Python :: 3"],
)
