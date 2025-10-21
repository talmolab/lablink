#!/bin/bash
echo "This is a multi-line script."
echo "It contains special characters like "quotes", \backslashes, and $dollarsigns."
# This is a comment
export VAR="some_value"
if [ "$VAR" = "some_value" ]; then
    echo "Variable test passed."
fi
