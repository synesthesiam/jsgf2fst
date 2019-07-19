#!/usr/bin/env bash
set -e

# Directory of *this* script
this_dir="$( cd "$( dirname "$0" )" && pwd )"

venv="${this_dir}/.venv"

if [[ -d "${venv}" ]]; then
    echo "Re-creating virtual environment at ${venv}"
    rm -rf "${venv}"
    python3 -m venv "${venv}"
fi

source "${venv}/bin/activate"

# openfst
build_dir="${this_dir}/build"
openfst_dir="${build_dir}/openfst-1.6.9"

# Copy build artifacts into virtual environment
cp -R "${openfst_dir}"/build/bin/* "${venv}/bin/"
cp -R "${openfst_dir}"/build/include/* "${venv}/include/"
cp -R "${openfst_dir}"/build/lib/*.so* "${venv}/lib/"

python3 -m pip install \
        --global-option=build_ext --global-option="-L${venv}/lib" \
        -r "${this_dir}/requirements.txt"
