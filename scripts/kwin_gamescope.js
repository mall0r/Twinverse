// Script KWin: distribui cada instância gamescope em um monitor diferente (modo fullscreen do GUI)

function getGamescopeClients() {
  var allClients = workspace.windowList();
  var gamescopeClients = [];
  for (var i = 0; i < allClients.length; i++) {
    if (allClients[i].resourceClass == "gamescope") {
      gamescopeClients.push(allClients[i]);
    }
  }
  return gamescopeClients;
}

function gamescopePerMonitor() {
  var gamescopeClients = getGamescopeClients();
  var screens = workspace.screens;
  var totalScreens = screens.length;

  // Só permite uma instância por monitor
  var count = Math.min(gamescopeClients.length, totalScreens);

  for (var i = 0; i < count; i++) {
    var monitor = screens[i];
    var monitorX = monitor.geometry.x;
    var monitorY = monitor.geometry.y;
    var monitorWidth = monitor.geometry.width;
    var monitorHeight = monitor.geometry.height;

    gamescopeClients[i].noBorder = true;
    gamescopeClients[i].frameGeometry = {
      x: monitorX,
      y: monitorY,
      width: monitorWidth,
      height: monitorHeight,
    };
  }
}

// Atualiza sempre que uma janela é adicionada/removida
workspace.windowAdded.connect(gamescopePerMonitor);
workspace.windowRemoved.connect(gamescopePerMonitor);

// Este script deve ser chamado pelo sistema apenas quando a opção "fullscreen" do GUI estiver ativada.
