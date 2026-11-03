import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

/**
 * 全局错误边界：捕获子组件树任意渲染/生命周期异常，
 * 避免生产环境一个组件报错导致整页白屏。
 * React 19 下仍采用 class 组件 + getDerivedStateFromError + componentDidCatch。
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // 上报到控制台，便于排查；后续可接入日志上报服务
    console.error('[ErrorBoundary] 捕获到渲染异常:', error)
    console.error('[ErrorBoundary] 组件堆栈:', errorInfo.componentStack)
  }

  handleReload = () => {
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }
      return (
        <div
          style={{
            minHeight: '100vh',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 16,
            padding: 24,
            fontFamily: 'system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
            color: '#1f2937',
            background: '#f9fafb',
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: 40, lineHeight: 1 }}>⚠️</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>页面出错了</div>
          <div
            style={{
              fontSize: 14,
              color: '#6b7280',
              maxWidth: 520,
              wordBreak: 'break-all',
              whiteSpace: 'pre-wrap',
            }}
          >
            {this.state.error?.message || '发生了未知错误'}
          </div>
          <button
            onClick={this.handleReload}
            style={{
              marginTop: 8,
              padding: '10px 24px',
              fontSize: 14,
              fontWeight: 500,
              color: '#fff',
              background: '#16a34a',
              border: 'none',
              borderRadius: 8,
              cursor: 'pointer',
            }}
          >
            刷新页面
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
