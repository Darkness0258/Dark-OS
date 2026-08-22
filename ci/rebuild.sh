#!/bin/bash
docker run --privileged -v "d:/Projects/Dark OS:/workspace" -v "d:/Projects/Dark OS/out:/workspace/out" darkos-builder 2>&1 | tail -5
