"""
from: https://github.com/harrysharma1/chmod-calculator

MIT License

Copyright (c) 2023 Harry Sharma

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Usage:

import chmod
a = chmod.ChmodConversion()
# Octal to Symbolic
print(a.int_to_perm(172))
# Symbolic to Octal
print(a.perm_to_int("--xrwx-w-"))
"""

import re

class ChmodConversion:

    def __init__(self) -> None:
        pass

    def int_to_perm(self, x: int):
        chmod_map_int = {
            0: "---",
            1: "--x",
            2: "-w-",
            3: "-wx",
            4: "r--",
            5: "r-x",
            6: "rw-",
            7: "rwx",
        }
        o = x % 10
        g = int((x / 10) % 10)
        u = int((x / 100) % 10)
        l = [u, g, o]
        s = ""
        for i in l:
            if i in chmod_map_int.keys():
                s += chmod_map_int[i]
            else:
                return "Incorrect value"
        return s

    def perm_to_int(self, x: str):
        regex = re.compile("((---)|(--x)|(-w-)|(-wx)|(r--)|(r-x)|(rw-)|(rwx)){3}")
        chmod_map_perm = {
            "---": 0,
            "--x": 1,
            "-w-": 2,
            "-wx": 3,
            "r--": 4,
            "r-x": 5,
            "rw-": 6,
            "rwx": 7,
        }
        if len(x) == 0:
            return "Empty string"
        if len(x) % 9 != 0 and len(x) % 6 != 0 and len(x) % 3 != 0:
            return "Incorrect length"
        u = x[:3]
        g = x[3:6]
        o = x[6:9]
        l = [u, g, o]
        s = ""
        error = []
        for i in l:
            if i in chmod_map_perm.keys():
                s += f"{chmod_map_perm[i]}"
            else:
                if i != "":
                    if re.match(regex, i) is None:
                        error.append(
                            f"{i}: Incorrect format (has to be in this format - rwx)"
                        )
        if len(s) < 3:
            error_string = ""
            for i in error:
                error_string += f"{i}\n"
            return error_string
        else:
            return s
