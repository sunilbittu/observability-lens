'use strict';
// node -r tracemelt/register app.js
// Starts telemetry before the application loads, so its modules can be instrumented.
require('./index').init();
