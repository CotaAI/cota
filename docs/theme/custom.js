// COTA 文档自定义JavaScript

// 全局Mermaid管理器
window.CotaMermaid = {
    loaded: false,
    initialized: false,
    
    // 加载Mermaid库
    loadMermaid: function() {
        if (this.loaded) return Promise.resolve();
        
        return new Promise((resolve, reject) => {
            if (window.mermaid) {
                this.loaded = true;
                resolve();
                return;
            }
            
            console.log('Loading Mermaid library...');
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js';
            script.onload = () => {
                console.log('Mermaid library loaded successfully');
                this.loaded = true;
                resolve();
            };
            script.onerror = () => {
                console.error('Failed to load Mermaid library');
                reject(new Error('Failed to load Mermaid'));
            };
            document.head.appendChild(script);
        });
    },
    
    // 初始化Mermaid配置
    initialize: function() {
        if (this.initialized || !window.mermaid) return;
        
        console.log('Initializing Mermaid...');
        window.mermaid.initialize({
            startOnLoad: false,  // 重要：禁用自动启动
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
        
        this.initialized = true;
        console.log('Mermaid initialized');
    },
    
    // 渲染所有Mermaid图表
    renderAll: function() {
        if (!window.mermaid || !this.initialized) return;
        
        console.log('Searching for Mermaid diagrams...');
        
        // 使用更通用的选择器
        const selectors = [
            'pre code.language-mermaid',
            'code.language-mermaid', 
            'pre[class*="mermaid"]',
            'code[class*="mermaid"]'
        ];
        
        let found = 0;
        selectors.forEach(selector => {
            const codeBlocks = document.querySelectorAll(selector + ':not(.mermaid-processed)');
            console.log(`Found ${codeBlocks.length} elements with selector: ${selector}`);
            
            codeBlocks.forEach((codeBlock, index) => {
                this.renderSingle(codeBlock, found + index);
                found++;
            });
        });
        
        console.log(`Total Mermaid diagrams found: ${found}`);
        
        // 如果找到了图表，执行渲染
        if (found > 0) {
            setTimeout(() => {
                window.mermaid.run();
            }, 100);
        }
    },
    
    // 渲染单个图表
    renderSingle: function(codeBlock, index) {
        try {
            const mermaidCode = codeBlock.textContent.trim();
            if (!mermaidCode) return;
            
            console.log(`Processing diagram ${index}:`, mermaidCode.substring(0, 50) + '...');
            
            // 标记为已处理
            codeBlock.classList.add('mermaid-processed');
            
            // 创建容器
            const container = document.createElement('div');
            container.className = 'mermaid-container';
            container.setAttribute('data-index', index);
            
            // 创建Mermaid元素
            const mermaidElement = document.createElement('div');
            mermaidElement.className = 'mermaid';
            mermaidElement.textContent = mermaidCode;
            
            container.appendChild(mermaidElement);
            
            // 替换原始代码块
            const preElement = codeBlock.closest('pre') || codeBlock;
            if (preElement && preElement.parentNode) {
                preElement.parentNode.replaceChild(container, preElement);
                console.log(`Replaced diagram ${index}`);
            }
        } catch (error) {
            console.error('Error processing Mermaid diagram:', error);
        }
    }
};

// mdBook兼容的初始化函数
async function initializeCotaMermaid() {
    try {
        await window.CotaMermaid.loadMermaid();
        window.CotaMermaid.initialize();
        window.CotaMermaid.renderAll();
    } catch (error) {
        console.error('Failed to initialize Mermaid:', error);
    }
}

// 监听mdBook的页面变化
function setupMdBookObserver() {
    // 监听主要内容区域的变化
    const contentElement = document.querySelector('#content, .content, main, body');
    if (!contentElement) return;
    
    const observer = new MutationObserver((mutations) => {
        let shouldRender = false;
        
        mutations.forEach((mutation) => {
            if (mutation.type === 'childList') {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // 检查是否包含代码块
                        if (node.querySelector('pre, code') || 
                            node.matches && node.matches('pre, code')) {
                            shouldRender = true;
                        }
                    }
                });
            }
        });
        
        if (shouldRender) {
            console.log('Content changed, re-rendering Mermaid diagrams...');
            setTimeout(() => {
                window.CotaMermaid.renderAll();
            }, 500);
        }
    });
    
    observer.observe(contentElement, {
        childList: true,
        subtree: true
    });
    
    console.log('MdBook observer setup complete');
}

// 多重初始化策略
function initializeAll() {
    console.log('Initializing COTA documentation features...');
    
    // 初始化Mermaid
    initializeCotaMermaid();
    
    // 设置观察器
    setupMdBookObserver();
    
    // 延迟添加代码复制功能
    setTimeout(addCopyButtons, 1000);
}

// 添加代码复制功能
function addCopyButtons() {
    // 为所有代码块添加复制按钮（排除mermaid和已处理的代码块）
    const codeBlocks = document.querySelectorAll('pre code:not(.language-mermaid):not(.mermaid-processed):not(.copy-button-added)');
    console.log(`Adding copy buttons to ${codeBlocks.length} code blocks`);
    
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
        
        // 标记为已添加
        codeBlock.classList.add('copy-button-added');
    });
}

// 多重事件监听确保兼容性
document.addEventListener('DOMContentLoaded', initializeAll);

// 备用初始化（如果DOMContentLoaded已经触发）
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeAll);
} else {
    // DOM已经加载完成
    setTimeout(initializeAll, 100);
}

// mdBook特殊事件监听
window.addEventListener('load', function() {
    console.log('Window loaded, checking for Mermaid diagrams...');
    setTimeout(() => {
        if (window.CotaMermaid) {
            window.CotaMermaid.renderAll();
        }
    }, 500);
});

// 页面可见性变化时重新渲染（处理缓存问题）
document.addEventListener('visibilitychange', function() {
    if (!document.hidden && window.CotaMermaid && window.CotaMermaid.initialized) {
        setTimeout(() => {
            console.log('Page became visible, re-rendering Mermaid...');
            window.CotaMermaid.renderAll();
        }, 200);
    }
});

function setupExternalLinks() {
    // 添加外链图标
    const externalLinks = document.querySelectorAll('a[href^="http"]:not([href*="' + window.location.hostname + '"]):not(.external-processed)');
    externalLinks.forEach(function(link) {
        link.innerHTML += ' <i class="fa fa-external-link" style="font-size: 0.8em; margin-left: 0.2em;"></i>';
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
        link.classList.add('external-processed');
    });
}

// 在初始化时设置外链
setTimeout(setupExternalLinks, 1500);

// 调试功能：手动渲染Mermaid
window.debugMermaid = function() {
    console.log('=== Mermaid Debug Info ===');
    console.log('Mermaid loaded:', !!window.mermaid);
    console.log('CotaMermaid initialized:', window.CotaMermaid?.initialized);
    
    // 搜索所有可能的mermaid元素
    const allSelectors = [
        'pre code.language-mermaid',
        'code.language-mermaid',
        'pre[class*="mermaid"]',
        'code[class*="mermaid"]',
        '.hljs.language-mermaid',
        'pre .hljs.language-mermaid'
    ];
    
    allSelectors.forEach(selector => {
        const elements = document.querySelectorAll(selector);
        console.log(`Selector "${selector}": found ${elements.length} elements`);
        elements.forEach((el, i) => {
            console.log(`  Element ${i}:`, el.textContent.substring(0, 100) + '...');
        });
    });
    
    // 强制重新渲染
    if (window.CotaMermaid) {
        window.CotaMermaid.renderAll();
    }
};

// 页面加载完成后显示调试信息
setTimeout(() => {
    console.log('COTA Documentation loaded. Use window.debugMermaid() for debugging.');
    if (window.CotaMermaid) {
        console.log('CotaMermaid status:', {
            loaded: window.CotaMermaid.loaded,
            initialized: window.CotaMermaid.initialized
        });
    }
}, 2000);

// 改进搜索体验
if (window.elasticlunr) {
    // 自定义搜索权重
    console.log('Search engine loaded with custom weights');
}
