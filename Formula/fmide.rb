class Fmide < Formula
  desc "Command-line access to fmIDE in FileMaker Pro"
  homepage "https://github.com/fmIDE/fmIDE-CLI"
  url "https://github.com/fmIDE/fmIDE-CLI/archive/refs/tags/v0.4.4.tar.gz"
  sha256 "87e929b2e0ad8fb60b99433408c68dd2c416a67ba8838c8d34704fc66122472f"
  license "MIT"

  depends_on :macos
  depends_on "python@3.14"

  def install
    libexec.install "fmide", "fmide_cli"
    inreplace libexec/"fmide", "#!/usr/bin/env python3", "#!#{formula_opt_bin("python@3.14")}/python3.14"
    bin.install_symlink libexec/"fmide"
    bin.install_symlink libexec/"fmide" => "fmIDE" unless (bin/"fmIDE").exist?
  end

  test do
    system formula_opt_bin("python@3.14")/"python3.14", "-c", <<~PYTHON
      import sys
      sys.path.insert(0, "#{libexec}")
      from fmide_cli.http_options import request_options
      from fmide_cli.urls import build_url
      expected = "fmp://$/MyFile?script=fmIDE&$layout_name=Home"
      assert build_url(request_options("-file=MyFile&$layout_name=Home")) == expected
      assert build_url(request_options("-file=MyFile&-$=layout_name=Home")) == expected
    PYTHON
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
