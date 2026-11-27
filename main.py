"""TrecoTunes — ponto de entrada.  Uso:  python main.py  [--test-audio | --version]"""
import sys

from treco.app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
