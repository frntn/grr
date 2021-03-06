#!/usr/bin/env python
# -*- mode: python; encoding: utf-8 -*-
"""Test the fileview interface."""



from grr.gui import api_call_handler_base
from grr.gui import gui_test_lib
from grr.gui import runtests_test
from grr.gui.api_plugins import vfs as api_vfs

from grr.lib import aff4
from grr.lib import flags
from grr.lib import rdfvalue
from grr.lib import test_lib
from grr.lib import utils
from grr.lib.rdfvalues import client as rdf_client


class TestFileView(gui_test_lib.GRRSeleniumTest):
  """Test the fileview interface."""

  def setUp(self):
    super(TestFileView, self).setUp()
    # Prepare our fixture.
    with self.ACLChecksDisabled():
      self.client_id = rdf_client.ClientURN("C.0000000000000001")
      test_lib.ClientFixture(self.client_id, self.token)
      gui_test_lib.CreateFileVersions(self.token)
      self.RequestAndGrantClientApproval("C.0000000000000001")

  def testOpeningVfsOfUnapprovedClientRedirectsToHostInfoPage(self):
    self.Open("/#/clients/C.0000000000000002/vfs/")

    # As we don't have an approval for C.0000000000000002, we should be
    # redirected to the host info page.
    self.WaitUntilEqual("/#/clients/C.0000000000000002/host-info",
                        self.GetCurrentUrlPath)
    self.WaitUntil(self.IsTextPresent,
                   "You do not have an approval for this client.")

  def testPageTitleChangesAccordingToSelectedFile(self):
    self.Open("/#/clients/C.0000000000000001/vfs/")
    self.WaitUntilEqual("GRR | C.0000000000000001 | /", self.GetPageTitle)

    # Select a folder in the tree.
    self.Click("css=#_fs i.jstree-icon")
    self.Click("css=#_fs-os i.jstree-icon")
    self.Click("css=#_fs-os-c i.jstree-icon")
    self.Click("link=Downloads")
    self.WaitUntilEqual("GRR | C.0000000000000001 | /fs/os/c/Downloads/",
                        self.GetPageTitle)

    # Select a file from the table.
    self.Click("css=tr:contains(\"a.txt\")")
    self.WaitUntilEqual("GRR | C.0000000000000001 | /fs/os/c/Downloads/a.txt",
                        self.GetPageTitle)

  def testVersionDropDownChangesFileContentAndDownloads(self):
    """Test the fileview interface."""

    # Set up multiple version for an attribute on the client for tests.
    with self.ACLChecksDisabled():
      for fake_time, hostname in [(gui_test_lib.TIME_0, "HostnameV1"),
                                  (gui_test_lib.TIME_1, "HostnameV2"),
                                  (gui_test_lib.TIME_2, "HostnameV3")]:
        with test_lib.FakeTime(fake_time):
          client = aff4.FACTORY.Open(
              u"C.0000000000000001", mode="rw", token=self.token)
          client.Set(client.Schema.HOSTNAME(hostname))
          client.Close()

    self.Open("/")

    self.Type("client_query", "C.0000000000000001")
    self.Click("client_query_submit")

    self.WaitUntilEqual(u"C.0000000000000001", self.GetText,
                        "css=span[type=subject]")

    # Choose client 1.
    self.Click("css=td:contains('0001')")

    # Go to Browse VFS.
    self.Click("css=a[grrtarget='client.vfs']")

    self.Click("css=#_fs i.jstree-icon")
    self.Click("css=#_fs-os i.jstree-icon")
    self.Click("css=#_fs-os-c i.jstree-icon")

    # Test file versioning.
    self.WaitUntil(self.IsElementPresent, "css=#_fs-os-c-Downloads")
    self.Click("link=Downloads")

    # Verify that we have the latest version in the table by default.
    self.assertTrue(
        gui_test_lib.DateString(gui_test_lib.TIME_2) in
        self.GetText("css=tr:contains(\"a.txt\")"))

    # Click on the row.
    self.Click("css=tr:contains(\"a.txt\")")
    self.WaitUntilContains("a.txt", self.GetText, "css=div#main_bottomPane h1")
    self.WaitUntilContains("HEAD", self.GetText,
                           "css=.version-dropdown > option[selected]")
    self.WaitUntilContains(
        gui_test_lib.DateString(gui_test_lib.TIME_2), self.GetText,
        "css=.version-dropdown > option:nth(1)")

    # Check the data in this file.
    self.Click("css=li[heading=TextView]")
    self.WaitUntilContains("Goodbye World", self.GetText,
                           "css=div.monospace pre")

    downloaded_files = []

    def FakeDownloadHandle(unused_self, args, token=None):
      _ = token  # Avoid unused variable linter warnings.
      aff4_path = args.client_id.ToClientURN().Add(args.file_path)
      age = args.timestamp or aff4.NEWEST_TIME
      downloaded_files.append((aff4_path, age))

      return api_call_handler_base.ApiBinaryStream(
          filename=aff4_path.Basename(), content_generator=xrange(42))

    with utils.Stubber(api_vfs.ApiGetFileBlobHandler, "Handle",
                       FakeDownloadHandle):
      # Try to download the file.
      self.Click("css=li[heading=Download]")

      self.WaitUntilContains(
          gui_test_lib.DateTimeString(gui_test_lib.TIME_2), self.GetText,
          "css=grr-file-download-view")
      self.Click("css=button:contains(\"Download\")")

      # Select the previous version.
      self.Click("css=select.version-dropdown > option:contains(\"%s\")" %
                 gui_test_lib.DateString(gui_test_lib.TIME_1))

      # Now we should have a different time.
      self.WaitUntilContains(
          gui_test_lib.DateTimeString(gui_test_lib.TIME_1), self.GetText,
          "css=grr-file-download-view")
      self.Click("css=button:contains(\"Download\")")

      self.WaitUntil(self.IsElementPresent, "css=li[heading=TextView]")

      # the FakeDownloadHandle method was actually called four times, since
      # a file download first sends a HEAD request to check user access.
      self.WaitUntil(lambda: len(downloaded_files) == 4)

    # Both files should be the same...
    self.assertEqual(downloaded_files[0][0],
                     u"aff4:/C.0000000000000001/fs/os/c/Downloads/a.txt")
    self.assertEqual(downloaded_files[2][0],
                     u"aff4:/C.0000000000000001/fs/os/c/Downloads/a.txt")
    # But from different times. The downloaded file timestamp is only accurate
    # to the nearest second. Also, the HEAD version of the file is downloaded
    # with age=NEWEST_TIME.
    self.assertEqual(downloaded_files[0][1], aff4.NEWEST_TIME)
    self.assertAlmostEqual(
        downloaded_files[2][1],
        gui_test_lib.TIME_1,
        delta=rdfvalue.Duration("1s"))

    self.Click("css=li[heading=TextView]")

    # Make sure the file content has changed. This version has "Hello World" in
    # it.
    self.WaitUntilContains("Hello World", self.GetText, "css=div.monospace pre")

  def testHexViewer(self):
    self.Open("/#clients/C.0000000000000001/vfs/fs/os/proc/10/")

    self.Click("css=td:contains(\"cmdline\")")
    self.Click("css=li[heading=HexView]:not(.disabled)")

    self.WaitUntilEqual("6c730068656c6c6f20776f726c6427002d6c", self.GetText,
                        "css=table.hex-area tr:first td")

    self.WaitUntilEqual("lshello world'-l", self.GetText,
                        "css=table.content-area tr:first td")

  def testSearchInputFiltersFileList(self):
    # Open VFS view for client 1.
    self.Open("/#c=C.0000000000000001&main=VirtualFileSystemView&t=_fs-os-c")

    # Navigate to the bin C.0000000000000001 directory
    self.Click("link=bin C.0000000000000001")

    # We need to await the initial file listing for the current directory,
    # since the infinite table will only issue one request at a time.
    # We could use WaitUntilNot to check that "Loading..." is not visible
    # anymore, but this could cause problems if "Loading..." is not shown yet.
    self.WaitUntilEqual("bash", self.GetText,
                        "css=table.file-list tr:nth(1) span")
    self.WaitUntilEqual("bsd-csh", self.GetText,
                        "css=table.file-list tr:nth(2) span")

    # Filter the table for bash (should match both bash and rbash)
    self.Type("css=input.file-search", "bash", end_with_enter=True)
    self.WaitUntilEqual("bash", self.GetText,
                        "css=table.file-list tr:nth(1) span")
    self.WaitUntilEqual("rbash", self.GetText,
                        "css=table.file-list tr:nth(2) span")
    self.WaitUntilEqual(2, self.GetCssCount,
                        "css=#content_rightPane table.file-list tbody > tr")

    # If we anchor cat at the start, we should only receive one result item.
    self.Type("css=input.file-search", "^cat", end_with_enter=True)
    self.WaitUntilEqual("cat", self.GetText,
                        "css=table.file-list tr:nth(1) span")
    self.assertEqual(
        1,
        self.GetCssCount("css=#content_rightPane table.file-list tbody > tr"))
    self.Click("css=tr:nth(1)")

    self.WaitUntilContains("cat", self.GetText, "css=#main_bottomPane h1")
    self.WaitUntil(self.IsTextPresent, "1026267")  # st_inode.

    # Lets download it.
    self.Click("css=li[heading=Download]")
    self.Click("css=button:contains(\"Collect from the client\")")

  def testExportToolHintIsDisplayed(self):
    self.Open("/#c=C.0000000000000001&main=VirtualFileSystemView")

    self.Click("css=li#_fs i.jstree-icon")
    self.Click("css=li#_fs-os i.jstree-icon")
    self.Click("css=li#_fs-os-c i.jstree-icon")
    self.Click("css=li#_fs-os-c-Downloads a")

    # Click on the row and on the Download tab.
    self.Click("css=tr:contains(\"a.txt\")")
    self.Click("css=li[heading=Download]")

    # Check that export tool download hint is displayed.
    self.WaitUntil(self.IsTextPresent, "/usr/bin/grr_export "
                   "--username %s file --path "
                   "aff4:/C.0000000000000001/fs/os/c/Downloads/a.txt --output ."
                   % self.token.username)


def main(argv):
  # Run the full test suite
  runtests_test.SeleniumTestProgram(argv=argv)


if __name__ == "__main__":
  flags.StartMain(main)
