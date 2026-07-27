---
# Project's title
title: "{{ replace .Name "-" " " | title }}"

# Featured image used for thumbnail and banner at detail page
featured_image: myimage.jpg

# Short summary of the project (one or two sentences)
summary: "One or two sentence project summary."

# When project started and ended
date_start: {{ .Date }}
date_end: {{ .Date }}

# Project website URL. Leave empty if none - shown as a "Website:" link when set.
project_url: ""

# Optional: grant/reference code, e.g. "NOO, MN-0009"
grant_code: "e.g. NOO, MN-0009"

# Optional: project budget, e.g. "81.730,00 EUR"
budget: "e.g. 81.730,00 EUR"

# Tags/Categories
tags:
- Deep Learning
- Energy
---

CONTENT

Consortium:

<!-- Embed an image/diagram from this project's own directory, e.g.:
{{< figure2 src="images/your-image.png" img-style="max-width:600px;width:100%;">}}
-->

<!-- Link related publications by their COBISS/arXiv/DOI id, e.g.:
## Publications:

{{< publicationlist ids="12345678,2203.10472v2">}}
-->

<!-- TODO: there's no equivalent shortcode yet to back-reference this project's related
content/results/*.md entries - that's planned but not yet implemented. -->
