#!/bin/bash

input_file="$0"

xsv select -- "path" "$input_file" | tail -n +2 | xargs -n1 -P32 bash -c 'dir="$(dirname ${0#https://s3-sa-east-1.amazonaws.com/mellf-speech/MELLF_PT_PROMPT/MICROSOFT/})"; mkdir -p "$dir" && (cd "$dir" && curl -O "$0")'
