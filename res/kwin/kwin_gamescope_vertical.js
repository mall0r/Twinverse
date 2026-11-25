const x = [
  [],
  [0],
  [0, 0.5],
  [0, 0.5, 0.5],
  [0, 0.5, 0, 0.5]
]

const y = [
  [],
  [0],
  [0, 0],
  [0, 0, 0.5],
  [0, 0, 0.5, 0.5]
]

const width = [
  [],
  [1],
  [0.5, 0.5],
  [0.5, 0.5, 0.5],
  [0.5, 0.5, 0.5, 0.5]
]

const height = [
  [],
  [1],
  [1, 1],
  [1, 0.5, 0.5],
  [0.5, 0.5, 0.5, 0.5]
]

function gamescopeAboveBelow() {
  var gamescopeClients = getGamescopeClients();
  // There is no active window while the desktop has the focus, and reading
  // it would throw and stop the placement of the instances.
  var activeWindow = workspace.activeWindow;
  var activeIsGamescope = !twinverseHasOverlay() &&
    activeWindow !== null && activeWindow !== undefined &&
    twinverseSlot(activeWindow) >= 0;
  for (var i = 0; i < gamescopeClients.length; i++) {
    if (activeIsGamescope) {
      gamescopeClients[i].keepAbove = true;
    } else {
      gamescopeClients[i].keepAbove = false;
    }
  }
}

function gamescopeSplitscreen() {
  var screens = twinverseScreens();
  twinversePositionClients(function (client, slot) {
    var groupIndex = Math.floor(slot / 4);
    var monitor = twinverseMonitor(screens, groupIndex);
    if (!monitor) return;

    var monitorX = monitor.geometry.x;
    var monitorY = monitor.geometry.y;
    var monitorWidth = monitor.geometry.width;
    var monitorHeight = monitor.geometry.height;

    var playerIndex = slot % 4 + 1;
    var playerCount = Math.min(4, twinverseLayout.instances.length - groupIndex * 4);

    if (client.fullScreen) client.fullScreen = false;
    if (client.maximizeMode && client.setMaximize) client.setMaximize(false, false);
    twinverseGeometry(client, {
      x: monitorX + Math.floor(x[playerCount][playerIndex - 1] * monitorWidth),
      y: monitorY + Math.floor(y[playerCount][playerIndex - 1] * monitorHeight),
      width: Math.floor(monitorWidth * width[playerCount][playerIndex - 1]),
      height: Math.floor(monitorHeight * height[playerCount][playerIndex - 1]),
    });
  });
  gamescopeAboveBelow();
}

twinverseInitialize(gamescopeSplitscreen);
workspace.windowActivated.connect(gamescopeAboveBelow);
