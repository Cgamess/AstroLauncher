
import argparse
import atexit
import ctypes
import os
import subprocess
import sys
import time

import requests

import cogs.AstroAPI as AstroAPI
import cogs.ValidateSettings as ValidateSettings
from cogs.AstroDaemon import AstroDaemon
from cogs.AstroDedicatedServer import AstroDedicatedServer
from cogs.AstroLogging import AstroLogging


"""
Build:
pyinstaller AstroLauncher.py -F --add-data "assets/*;." --icon=assets/astrolauncherlogo.ico
or
python BuildEXE.py
"""


class AstroLauncher():
    """ Starts a new instance of the Server Launcher"""

    def __init__(self, astroPath, disable_auto_update=False):
        self.astroPath = astroPath
        self.disable_auto_update = disable_auto_update
        self.version = "v1.2.3"
        self.latestURL = "https://github.com/ricky-davis/AstroLauncher/releases/latest"
        self.isExecutable = os.path.samefile(sys.executable, sys.argv[0])
        self.headers = AstroAPI.base_headers
        self.DaemonProcess = None
        self.DedicatedServer = AstroDedicatedServer(
            self.astroPath, self)

        AstroLogging.setup_logging(self.astroPath)

        AstroLogging.logPrint(
            f"Astroneer Dedicated Server Launcher {self.version}")
        self.check_for_update()

        AstroLogging.logPrint("Starting a new session")

        AstroLogging.logPrint("Checking the network configuration..")
        self.checkNetworkConfig()
        self.headers['X-Authorization'] = AstroAPI.generate_XAUTH(
            self.DedicatedServer.settings.ServerGuid)

        atexit.register(self.DedicatedServer.kill_server,
                        "Launcher shutting down")
        self.start_server()

    def check_for_update(self):
        url = "https://api.github.com/repos/ricky-davis/AstroLauncher/releases/latest"
        latestVersion = ((requests.get(url)).json())['tag_name']
        if latestVersion != self.version:
            AstroLogging.logPrint(
                f"UPDATE: There is a newer version of the launcher out! {latestVersion}")
            AstroLogging.logPrint(f"Download it at {self.latestURL}")
            if self.isExecutable and not self.disable_auto_update:
                self.autoupdate()

    def autoupdate(self):
        url = "https://api.github.com/repos/ricky-davis/AstroLauncher/releases/latest"
        x = (requests.get(url)).json()
        downloadFolder = os.path.dirname(sys.executable)
        for fileObj in x['assets']:
            downloadURL = fileObj['browser_download_url']
            downloadPath = os.path.join(downloadFolder, fileObj['name'])
            downloadCMD = ["powershell", '-executionpolicy', 'bypass', '-command',
                           'Write-Host "Starting download of latest AstroLauncher.exe..";', 'wait-process', str(
                               os.getpid()), ';',
                           'Invoke-WebRequest', downloadURL, "-OutFile", downloadPath,
                           ';', 'Start-Process', '-NoNewWindow', downloadPath]
            print(' '.join(downloadCMD))
            subprocess.Popen(downloadCMD, shell=True, creationflags=subprocess.DETACHED_PROCESS |
                             subprocess.CREATE_NEW_PROCESS_GROUP)
        time.sleep(2)
        self.DedicatedServer.kill_server("Auto-Update")

    def start_server(self):
        """
            Starts the Dedicated Server process and waits for it to be registered
        """
        self.DedicatedServer.ready = False
        oldLobbyIDs = self.DedicatedServer.deregister_all_server()
        AstroLogging.logPrint("Starting Server process...")
        time.sleep(3)
        startTime = time.time()
        self.DedicatedServer.start()
        self.DaemonProcess = AstroDaemon.launch(
            executable=self.isExecutable, consolePID=self.DedicatedServer.process.pid)

        # Wait for server to finish registering...
        apiRateLimit = 2
        while not self.DedicatedServer.registered:
            try:
                serverData = (AstroAPI.get_server(
                    self.DedicatedServer.ipPortCombo, self.headers))
                serverData = serverData['data']['Games']
                lobbyIDs = [x['LobbyID'] for x in serverData]
                if len(set(lobbyIDs) - set(oldLobbyIDs)) == 0:
                    time.sleep(apiRateLimit)
                else:
                    self.DedicatedServer.registered = True
                    del oldLobbyIDs
                    self.DedicatedServer.LobbyID = serverData[0]['LobbyID']

                if self.DedicatedServer.process.poll() is not None:
                    AstroLogging.logPrint(
                        "Server was forcefully closed before registration. Exiting....")
                    return False
            except:
                AstroLogging.logPrint(
                    "Failed to check server. Probably hit rate limit. Backing off and trying again...")
                apiRateLimit += 1
                time.sleep(apiRateLimit)

        doneTime = time.time()
        elapsed = doneTime - startTime
        AstroLogging.logPrint(
            f"Server ready with ID {self.DedicatedServer.LobbyID}. Took {round(elapsed,2)} seconds to register.")
        self.DedicatedServer.ready = True
        self.DedicatedServer.server_loop()

    def checkNetworkConfig(self):
        networkCorrect = ValidateSettings.test_network(
            self.DedicatedServer.settings.PublicIP, int(self.DedicatedServer.settings.Port))
        if networkCorrect:
            AstroLogging.logPrint("Server network configuration good!")
        else:
            AstroLogging.logPrint(
                "I can't seem to validate your network settings..", "warning")
            AstroLogging.logPrint(
                "Make sure to Port Forward and enable NAT Loopback", "warning")
            AstroLogging.logPrint(
                "If nobody can connect, Port Forward.", "warning")
            AstroLogging.logPrint(
                "If others are able to connect, but you aren't, enable NAT Loopback.", "warning")

        rconNetworkCorrect = not (ValidateSettings.test_network(
            self.DedicatedServer.settings.PublicIP, int(self.DedicatedServer.settings.ConsolePort)))
        if rconNetworkCorrect:
            AstroLogging.logPrint("Remote Console network configuration good!")
        else:
            AstroLogging.logPrint(
                f"SECURITY ALERT: Your console port ({self.DedicatedServer.settings.ConsolePort}) is Port Forwarded!", "warning")
            AstroLogging.logPrint(
                "SECURITY ALERT: This allows anybody to control your server.", "warning")
            AstroLogging.logPrint(
                "SECURITY ALERT: Disable this ASAP to prevent issues.", "warning")
            time.sleep(5)


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-p", "--path", help="Set the server folder path", type=str.lower)
        parser.add_argument("-d", "--daemon", dest="daemon",
                            help="Set the launcher to run as a Daemon", action='store_true')
        parser.add_argument("-U", "--noupdate", dest="noautoupdate",
                            help="Disable autoupdate if running as exe", action='store_true')

        parser.add_argument(
            "-c", "--consolepid", help="Set the consolePID for the Daemon", type=str.lower)
        parser.add_argument(
            "-l", "--launcherpid", help="Set the launcherPID for the Daemon", type=str.lower)
        args = parser.parse_args()
        if args.daemon:
            if args.consolepid and args.launcherpid:
                kernel32 = ctypes.WinDLL('kernel32')
                user32 = ctypes.WinDLL('user32')
                SW_HIDE = 0
                hWnd = kernel32.GetConsoleWindow()
                if hWnd:
                    user32.ShowWindow(hWnd, SW_HIDE)

                AstroDaemon().watchDog(args.launcherpid, args.consolepid)
            else:
                print("Insufficient launch options!")
        elif args.path:
            AstroLauncher(args.path, disable_auto_update=args.noautoupdate)
        else:
            AstroLauncher(os.getcwd(), disable_auto_update=args.noautoupdate)
    except KeyboardInterrupt:
        pass
