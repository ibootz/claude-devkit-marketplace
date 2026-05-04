// PreToolUse hook: 拦截工具使用，提醒使用 omp
const stdin = process.stdin;
let input = '';

stdin.on('data', (chunk) => {
  input += chunk;
});

stdin.on('end', () => {
  try {
    const data = JSON.parse(input);
    const toolName = data.tool_name || process.env.CLAUDE_TOOL_NAME;
    const toolInput = data.tool_input || {};

    // 检查是否是 omp 命令本身，如果是则允许
    if (toolName === 'Bash' && toolInput.command && toolInput.command.includes('omp -p')) {
      console.log(JSON.stringify({
        hookSpecificOutput: {
          permissionDecision: 'allow',
          permissionDecisionReason: 'omp 命令调用，允许执行'
        }
      }));
      return;
    }

    // 构建上下文提醒
    const contextMap = {
      'Read': '读取文件',
      'Edit': '编辑文件',
      'Write': '写入文件',
      'Grep': '搜索内容',
      'Bash': '执行命令'
    };

    const actionDesc = contextMap[toolName] || '执行操作';

    console.log(JSON.stringify({
      hookSpecificOutput: {
        permissionDecision: 'allow',
        permissionDecisionReason: `检测到${actionDesc}操作，提醒使用 omp`
      },
      additionalContext: `⚠️ 提醒：你正在直接使用 ${toolName} 工具${actionDesc}。
根据 using-omp 技能，你应该委托 omp 执行此操作：
  omp -p --tools "${toolName.toLowerCase()}" "【目标】...【上下文】...【期望输出】..."

如果你是在执行 omp 相关的辅助操作（如查看配置文件），可以忽略此提醒。
否则，请取消当前操作，改用 omp -p 委托执行。`
    }));
  } catch (e) {
    // 如果解析失败，允许工具执行
    console.log(JSON.stringify({
      hookSpecificOutput: {
        permissionDecision: 'allow',
        permissionDecisionReason: 'hook 解析失败，默认允许'
      }
    }));
  }
});
