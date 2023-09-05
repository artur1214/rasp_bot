s = ['a', 'b', 'c']
line, res = [], []
n = len(s)
for i in range(1, n + 1):
    for j in range(n):
        line += s[j]
        if len(line) == i:
            print(line)
            res.append(list(line))
            line.pop(0)
    line = []
print(res)