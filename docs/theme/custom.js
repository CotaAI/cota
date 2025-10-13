// COTA 文档自定义JavaScript

// 动态加载Mermaid
function loadMermaid() {
    if (window.mermaid) {
        initializeMermaid();
        return;
    }
    
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js';
    script.onload = function() {
        initializeMermaid();
    };
    document.head.appendChild(script);
}

// 初始化Mermaid
function initializeMermaid() {
    window.mermaid.initialize({
        theme: 'dark',
        themeVariables: {
            darkMode: true,
            primaryColor: '#1f2937',
            primaryTextColor: '#e5e7eb',
            primaryBorderColor: '#374151',
            lineColor: '#6b7280',
            secondaryColor: '#374151',
            tertiaryColor: '#111827',
            background: '#111827',
            mainBkg: '#1f2937',
            secondBkg: '#374151',
            tertiaryBkg: '#111827'
        },
        flowchart: {
            useMaxWidth: true,
            htmlLabels: true,
            curve: 'basis'
        },
        sequence: {
            useMaxWidth: true,
            wrap: true,
            messageFont: 'Menlo, Monaco, "Courier New", monospace'
        },
        gantt: {
            useMaxWidth: true
        },
        journey: {
            useMaxWidth: true
        },
        timeline: {
            useMaxWidth: true
        },
        gitgraph: {
            useMaxWidth: true
        }
    });
    
    // 查找并渲染所有Mermaid图表
    renderMermaidDiagrams();
}

// 渲染Mermaid图表
function renderMermaidDiagrams() {
    const mermaidCodeBlocks = document.querySelectorAll('pre code.language-mermaid, code.language-mermaid');
    
    mermaidCodeBlocks.forEach(function(codeBlock, index) {
        const mermaidCode = codeBlock.textContent.trim();
        
        // 创建容器div
        const mermaidDiv = document.createElement('div');
        mermaidDiv.className = 'mermaid-container';
        mermaidDiv.id = 'mermaid-' + index;
        
        // 创建实际的mermaid div
        const mermaidGraph = document.createElement('div');
        mermaidGraph.className = 'mermaid';
        mermaidGraph.textContent = mermaidCode;
        
        mermaidDiv.appendChild(mermaidGraph);
        
        // 替换原来的代码块
        const preElement = codeBlock.closest('pre') || codeBlock;
        preElement.parentNode.replaceChild(mermaidDiv, preElement);
    });
    
    // 渲染所有mermaid图表
    if (window.mermaid) {
        window.mermaid.run({
            querySelector: '.mermaid'
        });
    }
}

// 添加代码复制功能
document.addEventListener('DOMContentLoaded', function() {
    // 首先加载Mermaid
    loadMermaid();
    
    // 延迟执行代码复制功能，确保Mermaid渲染完成
    setTimeout(function() {
        // 为所有代码块添加复制按钮（排除mermaid代码块）
        const codeBlocks = document.querySelectorAll('pre code:not(.language-mermaid)');
    
    codeBlocks.forEach(function(codeBlock) {
        const pre = codeBlock.parentNode;
        const button = document.createElement('button');
        button.className = 'copy-button';
        button.textContent = '复制';
        button.style.cssText = `
            position: absolute;
            top: 5px;
            right: 5px;
            padding: 4px 8px;
            background: #007acc;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            font-size: 12px;
            z-index: 1;
        `;
        
        pre.style.position = 'relative';
        pre.appendChild(button);
        
        button.addEventListener('click', function() {
            navigator.clipboard.writeText(codeBlock.textContent).then(function() {
                button.textContent = '已复制!';
                setTimeout(function() {
                    button.textContent = '复制';
                }, 2000);
            });
            });
        });
    }, 1000);  // 延迟1秒执行
    
    // 添加外链图标
    const externalLinks = document.querySelectorAll('a[href^="http"]:not([href*="' + window.location.hostname + '"])');
    externalLinks.forEach(function(link) {
        link.innerHTML += ' <i class="fa fa-external-link" style="font-size: 0.8em; margin-left: 0.2em;"></i>';
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
    });
});

// 改进搜索体验
if (window.elasticlunr) {
    // 自定义搜索权重
    console.log('Search engine loaded with custom weights');
}
