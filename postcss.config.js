
const cssnano = require('cssnano')({ preset: 'default' });
const purgecss = require('@fullhuman/postcss-purgecss')({
  content: ['hugo_stats.json'],
  defaultExtractor: (content) => {
      const els = JSON.parse(content).htmlElements;
      return els.tags.concat(els.classes, els.ids);
  },
  // Bootstrap's collapse.js/dropdown.js add these classes purely at runtime (e.g. opening
  // the mobile navbar toggle), so they never appear in hugo_stats.json's static HTML scan
  // and would otherwise get purged, silently breaking the interaction.
  safelist: ['show', 'collapsing'],
});


module.exports = {
  plugins: [
    require('postcss-import'),
    //require('postcss-nested'),
    require('postcss-preset-env')(),
    ...(process.env.HUGO_ENVIRONMENT === 'production' ? [purgecss, cssnano] : [])
  ]
};
