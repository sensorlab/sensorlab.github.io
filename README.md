# sensorlab.ijs.si

New SensorLab webpage at [sensorlab.github.io](https://sensorlab.github.io)

## How to start developent and contribute?

### (Recommended) Develop inside container
- Install Docker
- run `make up` command

### Native
- Install Hugo "extended version" with SCSS support. [Instructions](https://gohugo.io/getting-started/installing/)
- install NodeJS. [Instructions](https://nodejs.org/en/download/)
- Install NodeJS dependencies using ``npm install``
- Run development server using ``npm start``

## How to contribute content?

### To add new funding project

1. Under `content/projects/` add new directory (e.g. `<brand-new-project>`).
2. Copy `archetypes/project.md` to `content/projects/<brand-new-project>/index.md`.
3. Edit content accordingly, provide logo, etc.
4. Optionally add supplemental material into `content/projects/<brand-new-project>/` directory.
5. Preview the outcome using `make up`.
6. Commit the changes.
