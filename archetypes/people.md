---
# personal photo
avatar: "person.jpg"

# position index is used for sorting/positioning on the website
position: 10

# Display name, can also put name in native language (UTF-8 supported).
# For a nickname/preferred name, embed it in quotes, e.g. Mihael "Miha" Mohorčič
title: "Firstname Lastname"

# Roles/positions: the first is primary and appears on the member card.
# All roles appear on the detailed profile, in this order.
# Legacy `role` (string or list) is supported when `roles` is empty or absent.
roles:
- "e.g. PhD Student, Postdoc, Research Fellow"
# - "Additional role"

# Organizations/Affiliations
organizations:
- name: Jožef Stefan Institute
  url: https://ijs.si

# COBISS/SICRIS identifier. Leave empty to ignore from publication generator
cobiss: ""

# The date when joined / departed from the lab. Empty or remove if not used
date_start: {{ .Date }}
date_end: {{ .Date }}

interests:
- Artificial Intelligence
- Computational Linguistics
- Information Retrieval


# Social/Academic Networking
# Links to social accounts and ways to interract, if any
# Examples: email, github, twitter/X, personal blog, facebook
social:
- text: Email
  link: mailto:test@example.org
- text: Twitter
  link: https://twitter.com/username
- text: Scholar
  link: https://scholar.google.co.uk/citations?user=sIwtMXoAAAAJ
- text: GitHub
  link: https://github.com/username
- text: Blog
  link: https://username.github.io


# Link to a PDF of your resume/CV from the About widget.
# To enable, copy your resume/CV to `static/files/cv.pdf` and uncomment the lines below.
# - text: CV
#   link: files/cv.pdf

# Optional organizational groups. Membership status is determined by the
# profile folder: content/people/active/ or content/people/alumni/.
user_groups:
- researchers
# - students
# - leaders
---

Write a short biography here.
