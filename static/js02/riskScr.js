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
        const resp = await fetch("/api/risk/list");
        const data = await resp.json();
        this.tableData = data;
        this.showTableData = this.tableData;
      }catch(err){
        console.error("数据库读取失败",err);
      }
    },
    async editClosedEvent({ row, column }) {
      const field = column.property;
      try {
        if(field === "remark"){
          const resp = await fetch("/api/risk/update_remark", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ id: row.id, remark: row.remark })
          })
          const ret = await resp.json();
          if(ret.code !== 0) alert("备注保存失败");
        } else if(field === "finishTime"){
          const resp = await fetch("/api/risk/update_finish_time", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ id: row.id, finishTime: row.finishTime })
          })
          const ret = await resp.json();
          if(ret.code !== 0) alert("整改完成时间保存失败");
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
        const resp = await fetch("/api/risk/upload_img", {
          method: "POST",
          body: formData
        });
        const ret = await resp.json();
        if(ret.code === 0){
          await this.updateImgField(this.uploadRow.id, this.uploadField, ret.url);
          this.uploadRow[this.uploadField] = ret.url;
        }else{
          alert(ret.msg || "上传失败");
        }
      }catch(err){
        console.error("上传异常", err);
        alert("上传失败，请检查后端服务");
      }
    },
    async updateImgField(id, field, url){
      await fetch("/api/risk/update_img", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ id, field, url })
      });
    },
    async deleteImg(row, field){
      if(!confirm("确定删除这张图片吗？")) return;
      const imgUrl = row[field];
      try{
        await fetch("/api/risk/delete_img", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ id: row.id, field, url: imgUrl })
        });
        row[field] = "";
      }catch(err){
        console.error("删除异常", err);
        alert("删除失败");
      }
    }
  }
})
