import win32serviceutil
import win32service
import win32event
import servicemanager


class TestService(win32serviceutil.ServiceFramework):

    _svc_name_ = "WorkstationMonitorTest"
    _svc_display_name_ = "Workstation Monitor Test"
    _svc_description_ = "Minimal PyWin32 service test"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)

        self.stop_event = win32event.CreateEvent(
            None,
            0,
            0,
            None
        )

    def SvcStop(self):
        self.ReportServiceStatus(
            win32service.SERVICE_STOP_PENDING
        )

        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):

        servicemanager.LogInfoMsg(
            "WorkstationMonitorTest started successfully"
        )

        win32event.WaitForSingleObject(
            self.stop_event,
            win32event.INFINITE
        )


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(TestService)