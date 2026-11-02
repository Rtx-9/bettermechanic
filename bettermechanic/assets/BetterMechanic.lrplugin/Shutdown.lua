-- the plugin is being reloaded, disabled or Lightroom quits: stop watching for photos (Init.lua)
require('Inbox').watcher = nil
