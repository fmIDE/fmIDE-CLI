class Fmide < Formula
  desc "Command-line access to fmIDE in FileMaker Pro"
  homepage "https://github.com/fmIDE/fmIDE-CLI"
  url "https://github.com/fmIDE/fmIDE-CLI/archive/refs/tags/v0.2.0.tar.gz"
  sha256 "695021df16e2c0214c121843063b0d7f78509e7667b15824fd265c2b53745bfe"
  license "MIT"

  depends_on :macos
  depends_on "python@3.14"

  def install
    libexec.install "fmide", "fmide_cli"
    inreplace libexec/"fmide", "#!/usr/bin/env python3", "#!#{Formula["python@3.14"].opt_bin}/python3.14"
    bin.install_symlink libexec/"fmide"
    bin.install_symlink libexec/"fmide" => "fmIDE" unless (bin/"fmIDE").exist?
  end

  test do
    ENV["FMIDE_SERVER_HOME"] = (testpath/"servers").to_s
    system bin/"fmide", "server", "add", "-tag", "brew-test", "-fmp", "19"
    assert_match "brew-test", shell_output("#{bin}/fmide server list")
    assert_match "fmp19", shell_output("#{bin}/fmide server brew-test status")
    system bin/"fmide", "server", "all", "terminate"
    assert_equal "fmIDE CLI #{version}", shell_output("#{bin}/fmide --version").strip
    assert_equal "fmp://$/fmIDE?script=fmIDE", shell_output("#{bin}/fmIDE -file fmIDE --dry-run").strip
    command = "#{bin}/fmide -fmp fmp26 -file 'My File' " \
              "--variable 'layout_name=Hello World' --dry-run"
    assert_equal "fmp26://$/My%20File?script=fmIDE&$layout_name=Hello%20World", shell_output(command).strip
  end
end
