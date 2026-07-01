import re

query = "can u explain slide 5"
m = re.search(r'(?i)\bslides?\s*(\d+)', query)
if m:
    print('Found slide number:', m.group(1))

query2 = "what is slide 30 about?"
m2 = re.search(r'(?i)\bslides?\s*(\d+)', query2)
if m2:
    print('Found slide number:', m2.group(1))
