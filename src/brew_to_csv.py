#!/usr/bin/env python3

import csv
import json
import os

os.system("brew info --json --installed > brew.json")
with open('brew.json') as f:
    pkgs = json.load(f)

with open('names.csv', 'w', newline='') as csvfile:
    fieldnames = ['name', 'version','desc']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    for p in pkgs:
        # print("name:", p['name'])
        # print("desc:", p['desc'])
        # print("version:", p['versions']['stable'])
        # print()            
        writer.writerow({
            'name': p['name'],
            'version': p['versions']['stable'],
            'desc': p['desc'],
        })
