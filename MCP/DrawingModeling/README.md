# 工程图证据与原生建模

安装、两个服务的配置及能力边界见[SolidWorks MCP](../Solidworks/README.md)。
依赖核心包与 requirements.txt。先提取 PDF，再形成有来源哈希、尺寸证据和未知项的 DrawingSpec。
调用 drawing_validate_spec 后才进行 drawing_build_solidworks。
本目录不附客户图纸、原生模型、商用模板或 CAD 软件。
配套[识图 Skill](../../skills/solidworks-drawing-modeling/SKILL.md)。
