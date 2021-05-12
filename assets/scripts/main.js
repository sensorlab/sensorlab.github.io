'use strict';

window.addEventListener('DOMContentLoaded', (ev) => {
  // Remove no-js class from HTML
  document.documentElement.className = document.documentElement.className.replace(/\bno-js\b/g, 'js');

  // Apply theme from written in localStorage
  //document.body.setAttribute(themeAttr, localStorage.getItem(themeKey) || 'light');
});
