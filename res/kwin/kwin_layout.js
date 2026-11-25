// Shared by the three layouts. KdeManager prepends twinverseLayout with the
// configured instance IDs, output connectors and the identity service address.
// A window is never assigned a slot based on workspace.windowList() order.
var twinverseWindows = [];
var twinversePlacement = null;
var twinverseUpdating = false;
var twinverseOutputs = [];
var twinverseOverlay = null;
var twinversePreviousActive = null;
var twinverseCenteringOverlay = false;

function twinverseRecord(client) {
  return twinverseWindows.find(function (record) { return record.client === client; });
}

function getGamescopeClients() {
  return twinverseWindows.filter(function (record) {
    return !record.removed && record.instance >= 0;
  }).map(function (record) { return record.client; });
}

function twinverseSlot(client) {
  var record = twinverseRecord(client);
  return record ? twinverseLayout.instances.indexOf(record.instance) : -1;
}

function twinverseScreens() {
  // Preserve connector indices even when an output disappears. Filtering out
  // a missing output would silently move the other instances to different slots.
  return twinverseLayout.monitors.map(function (name) {
    return workspace.screens.find(function (screen) { return screen.name === name; });
  });
}

function twinverseMonitor(screens, index) {
  return screens[index] || screens.find(function (screen) { return !!screen; });
}

function twinverseIsOverlay(client) {
  if (!client || !twinverseLayout.overlayTitles) return false;
  return twinverseLayout.overlayTitles.indexOf(client.caption) >= 0;
}

function twinverseHasOverlay() {
  return twinverseOverlay !== null;
}

function twinverseCenterOverlay(client) {
  if (!client || twinverseCenteringOverlay) return;
  var screens = twinverseScreens();
  var output = workspace.activeScreen || twinverseMonitor(screens, 0) || workspace.screens[0];
  if (!output) return;
  var current = client.frameGeometry;
  if (!current || current.width <= 0 || current.height <= 0) return;
  var area = output.geometry;
  var target = {
    x: area.x + Math.floor((area.width - current.width) / 2),
    y: area.y + Math.floor((area.height - current.height) / 2),
    width: current.width,
    height: current.height
  };
  if (current.x !== target.x || current.y !== target.y) {
    twinverseCenteringOverlay = true;
    try {
      client.frameGeometry = target;
    } finally {
      twinverseCenteringOverlay = false;
    }
  }
}

function twinverseTrackOverlay(client) {
  if (twinverseOverlay === client) return;
  twinversePreviousActive = workspace.activeWindow;
  twinverseOverlay = client;
  var clients = getGamescopeClients();
  for (var i = 0; i < clients.length; i++) {
    clients[i].keepAbove = false;
  }
  client.keepAbove = true;
  client.onAllDesktops = true;
  if (client.skipTaskbar !== undefined) client.skipTaskbar = true;
  if (client.skipPager !== undefined) client.skipPager = true;
  twinverseCenterOverlay(client);
  if (client.frameGeometryChanged) {
    client.frameGeometryChanged.connect(function () {
      if (twinverseOverlay === client) twinverseCenterOverlay(client);
    });
  }
  workspace.activeWindow = client;
}

function twinverseGeometry(client, geometry) {
  var current = client.frameGeometry;
  if (!client.noBorder) client.noBorder = true;
  if (!current || current.x !== geometry.x || current.y !== geometry.y ||
      current.width !== geometry.width || current.height !== geometry.height) {
    client.frameGeometry = geometry;
  }
}

function twinversePositionClients(position) {
  if (twinverseUpdating) return;
  twinverseUpdating = true;
  try {
    var clients = getGamescopeClients();
    for (var i = 0; i < clients.length; i++) {
      var slot = twinverseSlot(clients[i]);
      if (slot < 0) continue;
      if (twinverseLayout.placements !== undefined) {
        var placement = twinverseLayout.placements[String(twinverseRecord(clients[i]).instance)];
        if (!placement) continue;
        var output = workspace.screens.find(function (screen) { return screen.name === placement.monitor; });
        // Explicit layouts never fall back to a different connector.
        if (!output) continue;
        var rect = placement.rectangle;
        var geometry = output.geometry;
        if (clients[i].fullScreen) clients[i].fullScreen = false;
        if (clients[i].maximizeMode && clients[i].setMaximize) clients[i].setMaximize(false, false);
        twinverseGeometry(clients[i], {
          x: geometry.x + Math.floor(rect[0] * geometry.width),
          y: geometry.y + Math.floor(rect[1] * geometry.height),
          width: Math.floor(rect[2] * geometry.width),
          height: Math.floor(rect[3] * geometry.height)
        });
      } else {
        position(clients[i], slot);
      }
    }
  } finally {
    twinverseUpdating = false;
  }
}

function twinverseRefresh() {
  if (twinversePlacement) twinversePlacement();
}

function twinverseTrack(client) {
  if (twinverseIsOverlay(client)) {
    twinverseTrackOverlay(client);
    return;
  }
  if (twinverseRecord(client)) return;
  if (client.resourceClass !== "gamescope") {
    // Some backends publish the class or caption after windowAdded. Unrelated
    // windows must not trigger a redistribution of the managed instances.
    if (client.windowClassChanged) {
      client.windowClassChanged.connect(function () {
        if (client.resourceClass === "gamescope") twinverseTrack(client);
      });
    }
    if (client.captionChanged) {
      client.captionChanged.connect(function () {
        if (twinverseIsOverlay(client)) twinverseTrackOverlay(client);
      });
    }
    return;
  }

  var record = {client: client, instance: -1, removed: false};
  twinverseWindows.push(record);
  callDBus(twinverseLayout.service, twinverseLayout.path, twinverseLayout.interface,
    "ResolveInstance", String(client.pid), function (instance) {
      // The response can arrive after removal, or even after a replacement
      // window has appeared. Never attach an old reply to the replacement.
      if (record.removed || twinverseLayout.instances.indexOf(instance) < 0) return;
      record.instance = instance;
      if (client.frameGeometryChanged) client.frameGeometryChanged.connect(twinverseRefresh);
      if (client.fullScreenChanged) client.fullScreenChanged.connect(twinverseRefresh);
      if (client.maximizedChanged) client.maximizedChanged.connect(twinverseRefresh);
      print("Twinverse layout: instance", instance + 1, "PID", client.pid,
        "slot", twinverseSlot(client));
      twinverseRefresh();
    });
}

function twinverseRemoved(client) {
  if (twinverseOverlay === client) {
    twinverseOverlay = null;
    var previous = twinversePreviousActive;
    twinversePreviousActive = null;
    if (previous && getGamescopeClients().indexOf(previous) >= 0) {
      workspace.activeWindow = previous;
    }
    twinverseRefresh();
    return;
  }
  var record = twinverseRecord(client);
  if (!record) return;
  record.removed = true;
  twinverseWindows = twinverseWindows.filter(function (item) { return item !== record; });
  // The slot and the configured player count remain reserved. A replacement
  // window resolves the same instance ID, even if its PID or title changes.
  twinverseRefresh();
}

function twinverseInitialize(position) {
  twinversePlacement = position;
  workspace.windowAdded.connect(twinverseTrack);
  workspace.windowRemoved.connect(twinverseRemoved);
  function outputsChanged() {
    workspace.screens.forEach(function (output) {
      if (twinverseOutputs.indexOf(output) >= 0) return;
      twinverseOutputs.push(output);
      if (output.geometryChanged) output.geometryChanged.connect(twinverseRefresh);
    });
    twinverseRefresh();
  }
  if (workspace.screensChanged) workspace.screensChanged.connect(outputsChanged);
  outputsChanged();
  workspace.windowList().forEach(twinverseTrack);
}
