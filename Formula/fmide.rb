class Fmide < Formula
  desc "Command-line access to fmIDE in FileMaker Pro"
  homepage "https://github.com/fmIDE/fmIDE-CLI"
  url "https://github.com/fmIDE/fmIDE-CLI/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "aae0664a98f3076c9a7581270694bebf27a80378703a45ab87f21da4663b34cc"
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
    assert_equal "fmIDE CLI #{version}", shell_output("#{bin}/fmide --version").strip
    assert_equal "fmp://$/fmIDE?script=fmIDE", shell_output("#{bin}/fmIDE -file fmIDE --dry-run").strip
    assert_equal "fmp26://$/My%20File?script=fmIDE&$layout_name=Hello%20World",
                 shell_output("#{bin}/fmide -fmp fmp26 -file 'My File' --variable 'layout_name=Hello World' --dry-run").strip
  end
end
