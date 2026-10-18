You are coding one batch of chat-model replies. Everything you need is in this one file: `{BATCH_FILE}`. It contains the coding rubric followed by the items (each has a KEY, a SCENARIO, a QUESTION and a REPLY). Read that file and code every item exactly as the rubric says.

Rules:
- Read only that file. Do not list, search or open any other file or folder, and do not run any other commands.
- The file has exactly {N} items. Write your codes to `{CODES_FILE}`: exactly one JSON object per item ({N} lines), one per line, in the format given in the rubric's Output section, and nothing else in the file. Before finishing, check that every KEY in the file appears once in your output.
- When done, reply with only the word: done
