# sensorlab.ijs.si

New SensorLab webpage at [sensorlab.github.io](https://sensorlab.github.io) and [sensorlab.ijs.si](https://sensorlab.ijs.si)

## How to start development and contribute?

### (Recommended) Develop inside container
- Install Docker
- run `make up` command

### Native
- Install Hugo "extended version" with SCSS support. [Instructions](https://gohugo.io/getting-started/installing/)
- install NodeJS. [Instructions](https://nodejs.org/en/download/)
- Install NodeJS dependencies using ``npm install``
- Run development server using ``npm start``

## How to contribute content?

### Add or move a person

1. Run `hugo new content/people/active/<username>/index.md` for an active member,
   or use `content/people/alumni/<username>/index.md` for a former member.
2. Edit the profile and place their photo alongside `index.md`, referencing its
   filename in `avatar`.
3. When someone leaves, move their entire folder from `active/` to `alumni/` and
   fill in `date_end` when known. The folder determines placement on the People
   page; `user_groups` does not control membership status.

Keep usernames unique across both folders. Profile URLs remain
`/people/<username>/` when a person moves. Only `content/people/` needs an
`_index.md`; do not add one inside the grouping folders.

To check folder-based rendering and stable URLs, run
`python3 -m unittest discover -s scripts -p test_people_layout.py` with Hugo installed.

### Add a new funded project

1. Under `content/projects/`, add a new directory (e.g., `<brand-new-project>`).
2. Copy `archetypes/project.md` to `content/projects/<brand-new-project>/index.md`.
3. Edit content accordingly, provide logo, etc.
4. Optionally add supplemental material into the `content/projects/<brand-new-project>/` directory.
5. Preview the outcome using `make up`.
6. Commit the changes.
