// Script KWin: distribui cada instância gamescope em um monitor diferente (modo fullscreen do GUI)

function gamescopePerMonitor() {
  var screens = twinverseScreens();
  twinversePositionClients(function (client, slot) {
    var monitor = twinverseMonitor(screens, slot);
    if (!monitor) return;
    var monitorX = monitor.geometry.x;
    var monitorY = monitor.geometry.y;
    var monitorWidth = monitor.geometry.width;
    var monitorHeight = monitor.geometry.height;

    twinverseGeometry(client, {
      x: monitorX,
      y: monitorY,
      width: monitorWidth,
      height: monitorHeight,
    });
  });
}

twinverseInitialize(gamescopePerMonitor);

// Este script deve ser chamado pelo sistema apenas quando a opção "fullscreen" do GUI estiver ativada.
