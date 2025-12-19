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

function getGamescopeClients() {
  var allClients = workspace.windowList();
  var gamescopeClients = [];

  for (var i = 0; i < allClients.length; i++) {
    if (
      allClients[i].resourceClass == "gamescope"
    ) {
      gamescopeClients.push(allClients[i]);
    }
  }
  return gamescopeClients;
}

function numGamescopeClientsInOutput(output) {
  var gamescopeClients = getGamescopeClients();
  var count = 0;
  for (var i = 0; i < gamescopeClients.length; i++) {
    if (gamescopeClients[i].output == output) {
      count++;
    }
  }
  return count;
}

function gamescopeAboveBelow() {
  var gamescopeClients = getGamescopeClients();
  for (var i = 0; i < gamescopeClients.length; i++) {
    if (
      workspace.activeWindow.resourceClass == "gamescope"
    ) {
      gamescopeClients[i].keepAbove = true;
    } else {
      gamescopeClients[i].keepAbove = false;
    }
  }
}

function gamescopeSplitscreen() {
  var gamescopeClients = getGamescopeClients();
  var screens = workspace.screens;
  var totalScreens = screens.length;

  for (var i = 0; i < gamescopeClients.length; i++) {
    var groupIndex = Math.floor(i / 4); // grupo de 4 instâncias
    var monitor = screens[groupIndex % totalScreens]; // distribui entre monitores disponíveis

    var monitorX = monitor.geometry.x;
    var monitorY = monitor.geometry.y;
    var monitorWidth = monitor.geometry.width;
    var monitorHeight = monitor.geometry.height;

    var playerIndex = i % 4 + 1; // posição dentro do grupo
    var playerCount = Math.min(4, gamescopeClients.length - groupIndex * 4);

    gamescopeClients[i].noBorder = true;
    gamescopeClients[i].frameGeometry = {
      x: monitorX + x[playerCount][playerIndex - 1] * monitorWidth,
      y: monitorY + y[playerCount][playerIndex - 1] * monitorHeight,
      width: monitorWidth * width[playerCount][playerIndex - 1],
      height: monitorHeight * height[playerCount][playerIndex - 1],
    };
  }
  gamescopeAboveBelow();
}

workspace.windowAdded.connect(gamescopeSplitscreen);
workspace.windowRemoved.connect(gamescopeSplitscreen);
workspace.windowActivated.connect(gamescopeAboveBelow);
