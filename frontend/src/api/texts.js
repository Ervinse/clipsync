/**
 * 文本栏目 API
 */
import request from './request'

export default {
  // { items, total, max_texts }；长文本的 content 为 null，只有 preview
  list() {
    return request.get('/texts')
  },

  get(id) {
    return request.get(`/texts/${id}`)
  },

  // data：{ title, content }
  create(data) {
    return request.post('/texts', data)
  },

  // data：{ title, content, base_version }；base_version 为 null 表示直接覆盖，版本不一致返回 409
  update(id, data) {
    return request.put(`/texts/${id}`, data)
  },

  delete(id) {
    return request.delete(`/texts/${id}`)
  },
}
