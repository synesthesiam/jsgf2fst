#!/usr/bin/env python3
import os
import sys
import shutil
import tempfile
import subprocess
import logging


def main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser("fst2arpa")
    parser.add_argument("fst", help="Path to FST")
    args = parser.parse_args()

    print(fst2arpa(args.fst))


# -----------------------------------------------------------------------------


def fst2arpa(fst_path, arpa_path=None):
    """Converts a FST to ARPA model using opengrm."""

    for tool in ["ngramcount", "ngrammake", "ngramprint"]:
        if not shutil.which(tool):
            raise Exception(f"Missing {tool} (expected in PATH)")

    with tempfile.NamedTemporaryFile(mode="wb+") as count_file:
        # FST -> n-gram counts
        cmd = ["ngramcount", fst_path, count_file.name]
        logging.debug(cmd)

        try:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            logging.error(e.output.decode())
            raise e

        with tempfile.NamedTemporaryFile(mode="wb+") as model_file:
            count_file.seek(0)

            # n-gram counts -> n-gram model
            cmd = ["ngrammake", count_file.name, model_file.name]
            logging.debug(cmd)
            try:
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                logging.error(e.output.decode())
                raise e

            # n-gram model -> ARPA
            cmd = ["ngramprint", "--ARPA", model_file.name]
            logging.debug(cmd)

            if arpa_path is None:
                return subprocess.check_output(cmd)
            else:
                cmd.append(arpa_path)
                subprocess.check_call(cmd)


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
