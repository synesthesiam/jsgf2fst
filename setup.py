import os
import setuptools

this_dir = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_dir, "README.md"), "r") as readme_file:
    long_description = readme_file.read()

setuptools.setup(
    name="jsgf2fst",
    version="0.1.0",
    author="Michael Hansen",
    author_email="hansen.mike@gmail.com",
    url="https://github.com/synesthesiam/jsgf2fst",
    packages=setuptools.find_packages(),
    install_requires=["openfst==1.6.1", "pyjsgf==1.6.0"],
    classifiers=["Programming Language :: Python :: 3"],
    long_description=long_description,
    long_description_content_type="text/markdown",
)
