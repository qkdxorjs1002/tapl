# frozen_string_literal: true

# Synchronize release metadata and the platform-specific TAPL MCP runtime in the
# Homebrew formulas checked out by the release workflow.

files = ARGV
raise "Pass at least one Homebrew formula path" if files.empty?

version = ENV.fetch("RELEASE_VERSION")
wheel_url = ENV.fetch("WHEEL_URL")
wheel_sha256 = ENV.fetch("WHEEL_SHA256")

runtime_assets = {
  "macos" => {
    "arm" => [
      ENV.fetch("MCP_RUNTIME_MACOS_ARM64_URL"),
      ENV.fetch("MCP_RUNTIME_MACOS_ARM64_SHA256"),
    ],
    "intel" => [
      ENV.fetch("MCP_RUNTIME_MACOS_X86_64_URL"),
      ENV.fetch("MCP_RUNTIME_MACOS_X86_64_SHA256"),
    ],
  },
  "linux" => {
    "arm" => [
      ENV.fetch("MCP_RUNTIME_LINUX_ARM64_URL"),
      ENV.fetch("MCP_RUNTIME_LINUX_ARM64_SHA256"),
    ],
    "intel" => [
      ENV.fetch("MCP_RUNTIME_LINUX_X86_64_URL"),
      ENV.fetch("MCP_RUNTIME_LINUX_X86_64_SHA256"),
    ],
  },
}.freeze

RUNTIME_BEGIN = "# taplctl-mcp-runtime-begin"
RUNTIME_END = "# taplctl-mcp-runtime-end"
SMOKE_BEGIN = "# taplctl-mcp-smoke-begin"
SMOKE_END = "# taplctl-mcp-smoke-end"

def replacement_line(line, content)
  line.end_with?("\n") ? "#{content}\n" : content
end

def find_block_end(lines, start_index, indent)
  ((start_index + 1)...lines.length).find do |index|
    lines[index].match?(/^#{Regexp.escape(indent)}end\s*$/)
  end
end

def viewer_service_block(indent)
  [
    "#{indent}service do\n",
    "#{indent}  run [opt_bin/\"taplctl\", \"viewer\"]\n",
    "#{indent}  keep_alive true\n",
    "#{indent}  restart_delay 5\n",
    "#{indent}  log_path var/\"log/taplctl-viewer.log\"\n",
    "#{indent}  error_log_path var/\"log/taplctl-viewer.log\"\n",
    "#{indent}end\n",
  ]
end

def upsert_viewer_service_block(lines, indent)
  service_start = lines.index { |line| line.match?(/^#{Regexp.escape(indent)}service\s+do\s*$/) }
  if service_start
    service_end = find_block_end(lines, service_start, indent)
    raise "Could not find end of service block" unless service_end

    lines[service_start..service_end] = viewer_service_block(indent)
    return
  end

  install_start = lines.index { |line| line.match?(/^#{Regexp.escape(indent)}def install\s*$/) }
  raise "Could not find install block for service insertion" unless install_start

  install_end = find_block_end(lines, install_start, indent)
  raise "Could not find end of install block for service insertion" unless install_end

  insert_index = install_end + 1
  block = ["\n", *viewer_service_block(indent)]
  block << "\n" unless lines[insert_index]&.match?(/^\s*$/)
  lines.insert(insert_index, *block)
end

def runtime_resource_block(indent, assets)
  lines = ["#{indent}#{RUNTIME_BEGIN}\n"]
  { "macos" => "on_macos", "linux" => "on_linux" }.each do |os, os_dsl|
    lines << "#{indent}#{os_dsl} do\n"
    { "arm" => "on_arm", "intel" => "on_intel" }.each do |arch, arch_dsl|
      url, sha256 = assets.fetch(os).fetch(arch)
      lines.concat(
        [
          "#{indent}  #{arch_dsl} do\n",
          "#{indent}    resource \"mcp-runtime\" do\n",
          "#{indent}      url \"#{url}\"\n",
          "#{indent}      sha256 \"#{sha256}\"\n",
          "#{indent}    end\n",
          "#{indent}  end\n",
        ],
      )
    end
    lines << "#{indent}end\n"
  end
  lines << "#{indent}#{RUNTIME_END}\n"
  lines
end

def upsert_marked_block(lines, begin_marker, end_marker, replacement, insert_index)
  start_index = lines.index { |line| line.strip == begin_marker }
  end_index = lines.index { |line| line.strip == end_marker }
  if start_index || end_index
    raise "Incomplete marked block #{begin_marker}" unless start_index && end_index && end_index >= start_index

    lines[start_index..end_index] = replacement
  else
    lines.insert(insert_index, *replacement, "\n")
  end
end

def install_block(indent)
  [
    "#{indent}def install\n",
    "#{indent}  wheel = Pathname.glob(\"*.whl\").first\n",
    "#{indent}  raise \"Could not find taplctl wheel\" unless wheel\n",
    "\n",
    "#{indent}  wheelhouse = buildpath/\"wheelhouse\"\n",
    "#{indent}  wheelhouse.mkpath\n",
    "#{indent}  resource(\"mcp-runtime\").stage { wheelhouse.install Dir[\"*.whl\"] }\n",
    "#{indent}  runtime_packages = wheelhouse.glob(\"*.whl\").map do |runtime_wheel|\n",
    "#{indent}    runtime_wheel.basename.to_s.split(\"-\", 2).first.tr(\"_\", \"-\").downcase\n",
    "#{indent}  end\n",
    "#{indent}  resources.each do |resource|\n",
    "#{indent}    next if resource.name == \"mcp-runtime\"\n",
    "#{indent}    next if runtime_packages.include?(resource.name.tr(\"_\", \"-\").downcase)\n",
    "\n",
    "#{indent}    resource.stage { wheelhouse.install Dir[\"*.whl\"] }\n",
    "#{indent}  end\n",
    "\n",
    "#{indent}  dependency_wheels = wheelhouse.glob(\"*.whl\")\n",
    "#{indent}  raise \"Could not find dependency wheels\" if dependency_wheels.empty?\n",
    "#{indent}  virtualenv_create(libexec, \"python3.12\", system_site_packages: false)\n",
    "#{indent}  system \"python3.12\", \"-m\", \"pip\", \"--python=\#{libexec}/bin/python\", \"install\",\n",
    "#{indent}         \"--no-index\", \"--no-deps\", \"--no-compile\", *dependency_wheels\n",
    "#{indent}  system \"python3.12\", \"-m\", \"pip\", \"--python=\#{libexec}/bin/python\", \"install\",\n",
    "#{indent}         \"--no-index\", \"--no-deps\", \"--no-compile\", wheel\n",
    "#{indent}  bin.install_symlink libexec/\"bin/taplctl\"\n",
    "#{indent}  bin.install_symlink libexec/\"bin/tapl-mcp\"\n",
    "#{indent}end\n",
  ]
end

def smoke_test_block(indent)
  [
    "#{indent}  #{SMOKE_BEGIN}\n",
    "#{indent}  assert_path_exists bin/\"tapl-mcp\"\n",
    "#{indent}  system libexec/\"bin/python\", \"-c\",\n",
    "#{indent}         \"from mcp.server import MCPServer; from taplctl.mcp_server import create_server; assert create_server()\"\n",
    "#{indent}  #{SMOKE_END}\n",
  ]
end

def update_formula(file, version, wheel_url, wheel_sha256, runtime_assets)
  lines = File.readlines(file)

  version_index = lines.index { |line| line.match?(/^(\s*)version\s+[\"'][^\"']+[\"'](.*)$/) }
  raise "Could not update version in #{file}" unless version_index

  version_match = lines[version_index].match(/^(\s*)version\s+[\"'][^\"']+[\"'](.*)$/)
  lines[version_index] = replacement_line(
    lines[version_index],
    "#{version_match[1]}version \"#{version}\"#{version_match[2]}",
  )

  url_index = lines.index { |line| line.match?(/^(\s*)url\s+[\"'][^\"']+[\"'](.*)$/) }
  raise "Could not update url in #{file}" unless url_index

  url_match = lines[url_index].match(/^(\s*)url\s+[\"'][^\"']+[\"'](.*)$/)
  url_indent = url_match[1]
  lines[url_index] = replacement_line(lines[url_index], "#{url_indent}url \"#{wheel_url}\"")

  sha_index = lines.index { |line| line.match?(/^#{Regexp.escape(url_indent)}sha256\b/) }
  sha_line = "#{url_indent}sha256 \"#{wheel_sha256}\""
  if sha_index
    lines[sha_index] = replacement_line(lines[sha_index], sha_line)
  else
    sha_insert_index = version_index > url_index ? version_index + 1 : url_index + 1
    lines.insert(sha_insert_index, "#{sha_line}\n")
  end

  install_start = lines.index { |line| line.match?(/^(\s*)def install\s*$/) }
  raise "Could not find install block in #{file}" unless install_start

  indent = lines[install_start].match(/^(\s*)/)[1]
  runtime_lines = runtime_resource_block(indent, runtime_assets)
  upsert_marked_block(lines, RUNTIME_BEGIN, RUNTIME_END, runtime_lines, install_start)

  install_start = lines.index { |line| line.match?(/^#{Regexp.escape(indent)}def install\s*$/) }
  install_end = find_block_end(lines, install_start, indent)
  raise "Could not find end of install block in #{file}" unless install_end

  lines[install_start..install_end] = install_block(indent)
  upsert_viewer_service_block(lines, indent)

  test_start = lines.index { |line| line.match?(/^#{Regexp.escape(indent)}test\s+do\s*$/) }
  raise "Could not find test block in #{file}" unless test_start

  smoke_lines = smoke_test_block(indent)
  upsert_marked_block(lines, SMOKE_BEGIN, SMOKE_END, smoke_lines, test_start + 1)

  File.write(file, lines.join)
end

files.each { |file| update_formula(file, version, wheel_url, wheel_sha256, runtime_assets) }
