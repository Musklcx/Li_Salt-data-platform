new Vue({
  el: '#app',
  data () {
    return {
      tableData: [],
      showTableData: [],
      showPreview: false,
      previewUrl: "",
      uploadRow: null,
      uploadField: ""
    }
  },
  mounted(){
    this.loadDbData();
  },
  methods: {
    async loadDbData(){
      try{
        const resp = await request.get("/api/risk/list");
        this.tableData = resp;
        this.showTableData = this.tableData;
      }catch(err){
        console.error("数据库读取失败",err);
      }
    },
    async editClosedEvent({ row, column }) {
      const field = column.property;
      try {
        // request.js 已统一解包：失败会抛 Error，成功直接返回 data，无需判断 code
        if(field === "remark"){
          await request.post("/api/risk/update_remark", { id: row.id, remark: row.remark })
        } else if(field === "finishTime"){
          await request.post("/api/risk/update_finish_time", { id: row.id, finishTime: row.finishTime })
        }
      } catch(err) {
        console.error("保存异常", err);
        alert("保存失败！");
      }
    },
    previewImg(url){
      this.previewUrl = url;
      this.showPreview = true;
    },
    triggerUpload(row, field){
      this.uploadRow = row;
      this.uploadField = field;
      document.getElementById("hiddenFileInput").value = "";
      document.getElementById("hiddenFileInput").click();
    },
    async handleFileChange(e){
      const file = e.target.files[0];
      if(!file) return;
      if(!this.uploadRow || !this.uploadField) return;
      const maxSize = 5 * 1024 * 1024;
      if(file.size > maxSize){
        alert("图片不能超过5MB，请重新选择！");
        return;
      }
      try{
        const formData = new FormData();
        formData.append("file", file);
        formData.append("row_id", this.uploadRow.id);
        // 成功返回 data = {url}；失败抛 Error（msg 即后端提示）
        const ret = await request.upload("/api/risk/upload_img", formData);
        await this.updateImgField(this.uploadRow.id, this.uploadField, ret.url);
        this.uploadRow[this.uploadField] = ret.url;
      }catch(err){
        console.error("上传异常", err);
        alert(err.message || "上传失败，请检查后端服务");
      }
    },
    async updateImgField(id, field, url){
      await request.post("/api/risk/update_img", { id, field, url });
    },
    async deleteImg(row, field){
      if(!confirm("确定删除这张图片吗？")) return;
      const imgUrl = row[field];
      try{
        await request.post("/api/risk/delete_img", { id: row.id, field, url: imgUrl });
        row[field] = "";
      }catch(err){
        console.error("删除异常", err);
        alert("删除失败");
      }
    }
  }
})
